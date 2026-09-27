; 第 5 步冒烟测试：流水线骨架搭完、WB 段接好之后的第一次贯通跑。
; 验证时机：§8 第 5 步（四级流水线寄存器 + 寄存器堆写口改接 MEM/WB.rd）。
;
; 不含任何冒险——每一处读取都距写 k=4，所以前递、停顿、分支都还没搭也能跑。
; 数据 RAM 的 HT / OE 也不必接：本程序不用 OUT、不用 HLT。
;
; 为什么要有这一条：§2.1 那根线——寄存器堆的写地址必须在第 5 步从单周期版本的
;   Inst[15:12] 改接 MEM/WB.rd。接错时值全写进 R0，RAM 里是一片 0，
;   而 §9 没有第 5 步的条目（这一步原本只靠单步直接观察），最容易漏过去。
;
; 结果不在 OUT 上，全在 RAM 里。跑够 40 拍后停时钟，开 RAM 内容窗口：
;   0x10 = 0x11   0x11 = 0x22   0x12 = 0x33   0x13 = 0x44
;   0x14 = 0x07   0x20 = 0x11   其余全 0x00
;
; 拍数按最靠后的那条算，不按"一共 27 条"算：0x1A 的 STA 要到第 31 个时钟沿才写进 RAM
;   （它的 MEM 段是第 30 拍，写落在结束那一沿）。按 30 拍停会差一个沿，看到的 0x14 = 0x00
;   是那一下还没落，不是写错。
;
;   0x10-0x13 四格验 STA 的地址与数据源（08-0B 的写 Rd 的那条是 LDI）；
;   0x20 那道值来自 0C 的 LD，走过 MemRead mux 的 MemData 那一路——两个输入接反时
;     它会是地址 0x10 而不是数据 0x11；
;   0x14 那道值来自 16 的 ADD，走 MemRead mux 的 ALUResult 那一路。
;
; 出错时的症状：0x10-0x13 全 0 → 写地址接了 Inst[15:12]；四格全 0x11 → 写数据 mux
;   取错口（STA 的数据源在 [11:8]，走 A 口）；0x20 = 0x10 → MemRead mux 两极接反；
;   0x20 = 0x00 → RAM 的 DataOut 没接到 MEM/WB.MemData；0x14 = 0x11 → ADD 没写寄存器；
;   0x14 = 0x00 → 先查拍数（上一条），排除了再看 ADD 算出来是 0 —— 全文只有这一条 ADD 真走
;     ALU 运算，其余指令的 ALUop 都是 PASS.A/PASS.B 直通，所以这一格验的是 ALUop=0000 那一路；
;   出现这张表之外的非 0 字 → 有指令在不该写的时候写了 RAM。值等于地址的那种（0x22 = 0x22、
;   0x03 = 0x03）说明写发生的那一拍地址和数据取自同一处，先查 store 口的写使能是不是
;   EX/MEM.MemWrite、DataIn 是不是 EX/MEM.WriteData（见 docs/datapath.md §2.5 / §3.6）。
;
; ROM 0x1B 之后是 0，即保留码 op=0000（空操作，不写 RAM），所以程序跑过末尾会一直空转，
; RAM 内容停在上面那张表上不动。

        LDI R1, 0x11
        LDI R2, 0x22
        LDI R3, 0x33
        LDI R4, 0x44
        STA R1, 0x10     ; RAM[0x10] = 0x11
        STA R2, 0x11     ; RAM[0x11] = 0x22
        STA R3, 0x12     ; RAM[0x12] = 0x33
        STA R4, 0x13     ; RAM[0x13] = 0x44

        LDI R5, 0x10
        LDI R6, 0
        LDI R7, 0
        LDI R8, 0
        LD  R9, [R5]     ; R9 = RAM[0x10] = 0x11
        LDI R10, 0
        LDI R11, 0
        LDI R12, 0
        STA R9, 0x20     ; RAM[0x20] = 0x11（走过 MemRead mux 的 MemData 那一路）

        LDI R13, 3
        LDI R14, 4
        LDI R15, 0
        LDI R0, 0
        LDI R6, 0        ; 填充：把 11 / 12 与 16 的距离推到 k=4
        ADD R1, R13, R14 ; R1 = 7
        LDI R7, 0
        LDI R8, 0
        LDI R10, 0
        STA R1, 0x14     ; RAM[0x14] = 0x07（走过 MemRead mux 的 ALUResult 那一路）
