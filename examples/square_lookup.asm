; 平方表查表: 求 squares[3]，OUT = 9 (0x09)
; 验证时机：§8 第 7 步。含 load-use——14 的 OUT 紧跟 13 的 LD，且 OUT 的源在 ID 读口，
;           MEM/WB 前递也来不及，必须插气泡。无分支、无 k=3。
; **这是 load-use 的首选判据**：漏插气泡则输出 0x00 而非 0x09。
;   （hazard_k3.asm 的 LDA→OUT 也考这一项，但那个 0x00 与 k=3 没修好同值、两种成因要一起查。）
;   详见 README.md 的判据表。
; 1) 先把 0²..7² = 0,1,4,9,16,25,36,49 填进 RAM 0x20..0x27（STA 绝对寻址）
; 2) 计算地址 = 基址 0x20 + 索引 3 = 0x23，再 LD 间接读出
; 寄存器约定:
;   R1 = 临时（填表值）
;   R2 = 表基址 0x20
;   R3 = 索引
;   R4 = 地址 = 基址 + 索引
;   R5 = 查表结果

        ; --- 填充平方表 ---
        LDI R1, 0
        STA R1, 0x20
        LDI R1, 1
        STA R1, 0x21
        LDI R1, 4
        STA R1, 0x22
        LDI R1, 9
        STA R1, 0x23
        LDI R1, 16
        STA R1, 0x24
        LDI R1, 25
        STA R1, 0x25
        LDI R1, 36
        STA R1, 0x26
        LDI R1, 49
        STA R1, 0x27

        ; --- 查表 squares[3] ---
        LDI R2, 0x20     ; 基址
        LDI R3, 3        ; 索引
        ADD R4, R2, R3   ; 地址 = 0x20 + 3 = 0x23
        LD  R5, [R4]     ; R5 = RAM[0x23] = 9

        OUT R5           ; 9
        HLT
