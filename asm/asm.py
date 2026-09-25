#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8 位 RISC CPU 汇编器（v2，24 位定长指令 / 16 个寄存器 / 三操作数）

用法:
    python asm.py <input.asm> [output_prefix]

生成:
    <prefix>.lst  汇编清单（地址 / 机器码 / 源码）
    <prefix>.mem  Logisim ROM 镜像（"v2.0 raw" 格式，可直接 Load Image）

自检:
    python asm.py --selftest   跑 20 条黄金字节断言 + 标签解析 + 边界检查，全部通过退出码 0

编码规范见 docs/isa.md §4。
"""
from __future__ import annotations

import sys
import os
import re

# ---------------------------------------------------------------------------
# 常量（位布局见 docs/isa.md §4）
# ---------------------------------------------------------------------------
(OP_ALUR, OP_ALUM, OP_LDA, OP_STA, OP_LD, OP_ST,
 OP_BZ, OP_BNZ, OP_JMP, OP_OUT, OP_HLT) = range(0xB)

# 指令 ROM 容量（256×24）。PC 是 8 位，程序只能占 0x00–0xFF，超出的部分取不到。
ROM_WORDS = 256

# ALU 功能码（fn [19:16]）——两个 ALU opcode 族共用
FN_ADD, FN_ADC, FN_SUB, FN_SBC = 0, 1, 2, 3
FN_AND, FN_OR, FN_XOR = 4, 5, 6
FN_PASS_A, FN_PASS_B = 7, 8     # 直通：Result ← ALU.A / ALU.B

# 可作运算写在助记符里的 7 个功能（PASS 两个不直接暴露，由 MOV / LDI 用）
ALU_FN = {
    'ADD': FN_ADD, 'ADC': FN_ADC, 'SUB': FN_SUB, 'SBC': FN_SBC,
    'AND': FN_AND, 'OR': FN_OR, 'XOR': FN_XOR,
}

# 寄存器记号：[rR] + 0–15
REG_FULL_RE = re.compile(r'\s*[rR](1[0-5]|[0-9])\s*')


class AsmError(Exception):
    """带行号的汇编错误。"""
    def __init__(self, msg, lineno=None):
        self.lineno = lineno
        super().__init__(msg)


# ---------------------------------------------------------------------------
# 词法 / 解析
# ---------------------------------------------------------------------------
def parse_reg(tok: str) -> int:
    m = REG_FULL_RE.fullmatch(tok)
    if not m:
        raise AsmError(f"非法寄存器 '{tok}'（应为 R0–R15）")
    return int(m.group(1))


def parse_reg_bracketed(tok: str) -> int:
    """解析寄存器，容忍 [R2] 形式。"""
    t = tok.strip()
    if t.startswith('[') and t.endswith(']'):
        t = t[1:-1].strip()
    return parse_reg(t)


def looks_like_reg(tok: str) -> bool:
    return REG_FULL_RE.fullmatch(tok) is not None


def parse_num(tok: str) -> int:
    """十进制 / 0x / 0b。允许 5、#5 两种写法（`#` 是立即数前缀，不是注释符）。"""
    t = tok.strip()
    if t.startswith('#'):
        t = t[1:].strip()
    try:
        if t.lower().startswith('0x'):
            v = int(t, 16)
        elif t.lower().startswith('0b'):
            v = int(t, 2)
        else:
            v = int(t, 10)
    except ValueError:
        raise AsmError(f"非法数值 '{tok}'")
    return v


def check_u8(v: int, what: str, lineno=None) -> int:
    if not (0 <= v <= 0xFF):
        raise AsmError(f"{what} {v} 超出 8 位范围（0–255）", lineno)
    return v


# ---------------------------------------------------------------------------
# 编码（位布局见 docs/isa.md §4）
# ---------------------------------------------------------------------------
def enc_alur(rd, rs1, rs2, fn):
    return (OP_ALUR << 20) | (fn << 16) | (rd << 12) | (rs1 << 8) | (rs2 << 4)

def enc_alum(rd, rs1, imm, fn):
    return (OP_ALUM << 20) | (fn << 16) | (rd << 12) | (rs1 << 8) | imm

def enc_mov(rd, rs1):          # PASS.A：Result ← Rs1，Rs2 填 0 被忽略
    return enc_alur(rd, rs1, 0, FN_PASS_A)

def enc_ldi(rd, imm):          # PASS.B：Result ← imm，Rs1 填 0 被忽略
    return enc_alum(rd, 0, imm, FN_PASS_B)

def enc_lda(rd, addr):
    return (OP_LDA << 20) | (rd << 12) | addr

# 两条 store 的数据寄存器**不在 rd 槽**，而在自己空着的源槽里：
#   STA 的 [11:8] 空着（地址占的是 [7:0]）→ 数据寄存器放 [11:8]（A 口）
#   ST  的 [7:4]  空着（地址占的是 [11:8]）→ 数据寄存器放 [7:4] （B 口）
# 于是 [15:12] 恒为 0：它对任何指令都只是目标槽，从不当源。见 docs/isa.md §4。
def enc_sta(rdata, addr):      # rdata = 数据寄存器（源）
    return (OP_STA << 20) | (rdata << 8) | addr

def enc_ld(rd, rs1):
    return (OP_LD << 20) | (rd << 12) | (rs1 << 8)

def enc_st(rdata, rs1):        # rdata = 数据寄存器（源）, rs1 = 地址寄存器
    return (OP_ST << 20) | (rs1 << 8) | (rdata << 4)

def enc_bz(rs1, addr):
    return (OP_BZ << 20) | (rs1 << 8) | addr

def enc_bnz(rs1, addr):
    return (OP_BNZ << 20) | (rs1 << 8) | addr

def enc_jmp(addr):
    return (OP_JMP << 20) | addr

def enc_out(rs1):
    return (OP_OUT << 20) | (rs1 << 8)

def enc_hlt():
    return OP_HLT << 20


# ---------------------------------------------------------------------------
# 单条指令 → 24 位机器码
# ---------------------------------------------------------------------------
def encode_instruction(mnemonic: str, ops: list[str], symbols, lineno=None) -> int:
    m = mnemonic.upper()

    # ALU 族：ADD/ADC/SUB/SBC/AND/OR/XOR，第三个操作数决定寄存器型还是立即数型
    if m in ALU_FN:
        if len(ops) != 3:
            raise AsmError(f"{m} 需要 3 个操作数（Rd, Rs1, Rs2 或 #imm）", lineno)
        rd = parse_reg(ops[0])
        rs1 = parse_reg(ops[1])
        fn = ALU_FN[m]
        if looks_like_reg(ops[2]):
            return enc_alur(rd, rs1, parse_reg(ops[2]), fn)
        imm = check_u8(parse_num(ops[2]), "立即数", lineno)
        return enc_alum(rd, rs1, imm, fn)

    if m == 'MOV':
        if len(ops) != 2:
            raise AsmError("MOV 需要 2 个操作数（Rd, Rs1）", lineno)
        return enc_mov(parse_reg(ops[0]), parse_reg(ops[1]))

    if m == 'LDI':
        if len(ops) != 2:
            raise AsmError("LDI 需要 2 个操作数（Rd, #imm）", lineno)
        rd = parse_reg(ops[0])
        imm = check_u8(parse_num(ops[1]), "立即数", lineno)
        return enc_ldi(rd, imm)

    if m == 'LDA':
        if len(ops) != 2:
            raise AsmError("LDA 需要 2 个操作数（Rd, addr）", lineno)
        rd = parse_reg(ops[0])
        addr = check_u8(parse_num(ops[1]), "地址", lineno)
        return enc_lda(rd, addr)

    if m == 'STA':
        if len(ops) != 2:
            raise AsmError("STA 需要 2 个操作数（数据源, addr）", lineno)
        rdata = parse_reg(ops[0])
        addr = check_u8(parse_num(ops[1]), "地址", lineno)
        return enc_sta(rdata, addr)

    if m == 'LD':
        if len(ops) != 2:
            raise AsmError("LD 需要 2 个操作数（Rd, [Rs1]）", lineno)
        rd = parse_reg(ops[0])
        rs1 = parse_reg_bracketed(ops[1])
        return enc_ld(rd, rs1)

    if m == 'ST':
        if len(ops) != 2:
            raise AsmError("ST 需要 2 个操作数（数据源, [地址寄存器]）", lineno)
        rdata = parse_reg(ops[0])
        rs1 = parse_reg_bracketed(ops[1])
        return enc_st(rdata, rs1)

    if m == 'BZ':
        if len(ops) != 2:
            raise AsmError("BZ 需要 2 个操作数（Rs1, addr）", lineno)
        rs1 = parse_reg(ops[0])
        addr = resolve_target(ops[1], symbols, lineno)
        return enc_bz(rs1, addr)

    if m == 'BNZ':
        if len(ops) != 2:
            raise AsmError("BNZ 需要 2 个操作数（Rs1, addr）", lineno)
        rs1 = parse_reg(ops[0])
        addr = resolve_target(ops[1], symbols, lineno)
        return enc_bnz(rs1, addr)

    if m == 'JMP':
        if len(ops) != 1:
            raise AsmError("JMP 需要 1 个操作数（addr）", lineno)
        addr = resolve_target(ops[0], symbols, lineno)
        return enc_jmp(addr)

    if m == 'OUT':
        if len(ops) != 1:
            raise AsmError("OUT 需要 1 个操作数（Rs1）", lineno)
        return enc_out(parse_reg(ops[0]))

    if m == 'HLT':
        if ops:
            raise AsmError("HLT 不接受操作数", lineno)
        return enc_hlt()

    raise AsmError(f"未知助记符 '{mnemonic}'", lineno)


def resolve_target(tok: str, symbols, lineno=None) -> int:
    """分支/跳转目标：标签或数值。"""
    t = tok.strip()
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', t):
        if t not in symbols:
            raise AsmError(f"未定义的标签 '{t}'", lineno)
        return check_u8(symbols[t], f"标签 '{t}' 的地址", lineno)
    return check_u8(parse_num(t), "地址", lineno)


# ---------------------------------------------------------------------------
# 预处理 & 两遍扫描
# ---------------------------------------------------------------------------
def strip_comment(line: str) -> str:
    """`;` 到行尾是注释。`#` 不是注释符——它是立即数前缀（`ADD R1,R2,#5`）。"""
    i = line.find(';')
    if i != -1:
        line = line[:i]
    return line.strip()


def split_label(line: str):
    """返回 (label | None, 剩余部分)。"""
    if ':' in line:
        label, _, rest = line.partition(':')
        return label.strip(), rest.strip()
    return None, line.strip()


def split_operands(s: str) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in s.split(',') if p.strip()]


def tokenize(line: str):
    """返回 (label, mnemonic, ops) 或 None（空行）。"""
    line = strip_comment(line)
    if not line:
        return None
    label, rest = split_label(line)
    if not rest:
        return (label, None, [])   # 仅标签行
    parts = rest.split(None, 1)
    mnemonic = parts[0]
    ops_str = parts[1] if len(parts) > 1 else ''
    ops = split_operands(ops_str)
    return (label, mnemonic, ops)


def assemble_lines(lines) -> tuple[list[int], list[tuple[int, int, str]]]:
    """返回 (words, listing)。listing 项 = (addr, word, 源码)。"""
    # 先做行级预处理，保留原始行号用于报错
    parsed = []
    for lineno, raw in enumerate(lines, start=1):
        t = tokenize(raw)
        parsed.append((lineno, raw.rstrip(), t))

    # Pass 1: 建符号表
    symbols = {}
    addr = 0
    for lineno, raw, t in parsed:
        if t is None:
            continue
        label, mnemonic, ops = t
        if label:
            if label in symbols:
                raise AsmError(f"标签 '{label}' 重复定义", lineno)
            symbols[label] = addr
        if mnemonic is not None:   # 有指令才占一个地址
            addr += 1

    # Pass 2: 编码
    words = []
    listing = []
    addr = 0
    for lineno, raw, t in parsed:
        if t is None:
            continue
        label, mnemonic, ops = t
        if mnemonic is None:
            continue
        if addr >= ROM_WORDS:
            raise AsmError(
                f"程序超出指令 ROM 容量（上限 {ROM_WORDS} 条）", lineno)
        word = encode_instruction(mnemonic, ops, symbols, lineno)
        words.append(word)
        listing.append((addr, word, raw))
        addr += 1

    return words, listing


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def format_mem(words: list[int]) -> str:
    """Logisim ROM 镜像（v2.0 raw）：首行 'v2.0 raw'，随后按序 6 位十六进制值、空格分隔。"""
    out = ["v2.0 raw"]
    for i in range(0, len(words), 16):
        out.append(" ".join(f"{w:06x}" for w in words[i:i + 16]))
    return "\n".join(out) + "\n"


def format_listing(listing) -> str:
    lines = []
    for addr, word, src in listing:
        lines.append(f"{addr:02X}  {word:06X}  {src}")
    return "\n".join(lines) + "\n"


def assemble_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    words, listing = assemble_lines(lines)
    return words, listing


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def assemble_snippet(text: str) -> list[int]:
    """汇编一小段源码（无标签场景），返回机器码列表。"""
    words, _ = assemble_lines(text.splitlines())
    return words


def selftest() -> int:
    # 20 条断言：覆盖全部 11 个 opcode 与全部 9 个 fn。
    # 十六进制逐位对应 op|fn|rd|rs1|rs2/imm，读得出来才算钉死。
    # 两条 store 是唯一的例外：数据源占的是自己的源槽（STA→rs1、ST→rs2），rd 槽恒 0。
    cases = [
        # ---- ALU 寄存器型（op=0000）：fn 0–6 + MOV（PASS.A, fn=7）----
        ("ADD R1, R2, R3",   0x001230),
        ("SUB R4, R1, R5",   0x024150),
        ("SBC R1, R2, R3",   0x031230),
        ("AND R1, R2, R3",   0x041230),
        ("OR  R1, R2, R3",   0x051230),
        ("XOR R7, R7, R7",   0x067770),
        ("MOV R1, R2",       0x071200),
        # ---- ALU 立即数型（op=0001）：同 7 个 fn + LDI（PASS.B, fn=8）----
        ("ADD R1, R2, #5",   0x101205),
        ("ADC R15, R0, 0xFF", 0x11F0FF),   # `#` 可省；R15/R0 合法
        ("LDI R1, 5",        0x181005),
        ("LDI R2, 0b1010",   0x18200A),
        # ---- 访存 / 分支 / 其它 ----
        ("LDA R1, 0x2A",     0x20102A),
        ("STA R1, 0x2A",     0x30012A),   # 数据源 R1 在 [11:8]，rd 槽编 0
        ("LD R2, [R3]",      0x402300),
        ("ST R2, [R3]",      0x500320),   # 地址 R3 在 [11:8]，数据源 R2 在 [7:4]，rd 槽编 0
        ("BZ  R1, 0x10",     0x600110),
        ("BNZ R1, 0x10",     0x700110),
        ("JMP 0x00",         0x800000),
        ("OUT R15",          0x900F00),
        ("HLT",              0xA00000),
    ]
    failures = 0
    for src, expected in cases:
        try:
            words = assemble_snippet(src)
            got = words[0] if len(words) == 1 else None
        except AsmError as e:
            print(f"FAIL  {src!r:22} 异常: {e}")
            failures += 1
            continue
        if got != expected:
            print(f"FAIL  {src!r:22}  期望 {expected:06X}  实际 {got}")
            failures += 1
        else:
            print(f"ok    {src!r:22}  {got:06X}")

    # 标签解析测试
    try:
        words = assemble_snippet(
            "start: LDI R1, #1\n"
            "loop:  ADD R1, R1, R1\n"
            "       BNZ R1, loop\n"
            "       HLT\n"
        )
        assert len(words) == 4, f"指令条数错误: {len(words)}"
        assert words[2] == enc_bnz(1, 1), f"标签解析错误: {words[2]:06X}"
        print("ok    标签解析 (loop → 0x01)")
    except AsmError as e:
        print(f"FAIL  标签解析异常: {e}")
        failures += 1

    # 第三个操作数是寄存器还是立即数——两条路径必须给出不同机器码
    try:
        reg = assemble_snippet("ADD R1, R2, R3")[0]
        imm = assemble_snippet("ADD R1, R2, 3")[0]
        assert reg == enc_alur(1, 2, 3, FN_ADD), f"寄存器型错误: {reg:06X}"
        assert imm == enc_alum(1, 2, 3, FN_ADD), f"立即数型错误: {imm:06X}"
        print("ok    ADD 寄存器型 / 立即数型分派")
    except AsmError as e:
        print(f"FAIL  分派测试异常: {e}")
        failures += 1

    # 边界：正好 ROM_WORDS 条要能过，多一条要报错（PC 只有 8 位）
    try:
        assert assemble_snippet("\n".join(["HLT"] * ROM_WORDS)) == [enc_hlt()] * ROM_WORDS
        print(f"ok    正好 {ROM_WORDS} 条可用")
    except AsmError as e:
        print(f"FAIL  正好 {ROM_WORDS} 条被误拒: {e}")
        failures += 1

    try:
        assemble_snippet("\n".join(["HLT"] * (ROM_WORDS + 1)))
        print(f"FAIL  超出 ROM 容量（{ROM_WORDS} 条）未报错")
        failures += 1
    except AsmError:
        print(f"ok    超出 ROM 容量被拒（第 {ROM_WORDS + 1} 条报错）")

    if failures:
        print(f"\n{failures} 项失败")
        return 1
    print("\n全部通过")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv):
    if len(argv) >= 2 and argv[1] == '--selftest':
        return selftest()

    if len(argv) < 2:
        print(__doc__)
        return 2

    src = argv[1]
    if not os.path.exists(src):
        print(f"找不到文件: {src}", file=sys.stderr)
        return 2

    prefix = argv[2] if len(argv) >= 3 else os.path.splitext(src)[0]
    try:
        words, listing = assemble_file(src)
    except AsmError as e:
        loc = f"（第 {e.lineno} 行）" if e.lineno else ""
        print(f"汇编错误{loc}: {e}", file=sys.stderr)
        return 1

    if not words:
        print(f"汇编错误: {src} 里没有任何指令（只有注释或空行？）", file=sys.stderr)
        return 1

    lst_path = prefix + '.lst'
    mem_path = prefix + '.mem'
    out_dir = os.path.dirname(os.path.abspath(prefix))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    # newline='\n'：产物一律 LF。默认的换行转换会让 Windows 上写出 CRLF、
    # 别的平台上写出 LF，同一个源文件在不同机器上汇编出不同字节——那样
    # "重新汇编后 git status 干净 == 机器码没变" 这条判据就不成立了。
    # Logisim 自己 Save Image 写出的也是 LF（FileWriter 不做换行转换）。
    with open(lst_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(format_listing(listing))
    with open(mem_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(format_mem(words))

    print(f"汇编完成: {len(words)} 条指令")
    print(f"  清单:    {lst_path}")
    print(f"  ROM镜像: {mem_path}  （Logisim ROM 右键 → Load Image）")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
