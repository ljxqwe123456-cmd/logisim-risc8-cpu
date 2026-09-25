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
; 结果不在 OUT 上，全在 RAM 里。跑够 30 拍后停时钟，开 RAM 内容窗口：
;   0x10 = 0x11   0x11 = 0x22   0x12 = 0x33   0x13 = 0x44
;   0x14 = 0x07   0x20 = 0x11   其余全 0x00
;
;   0x10-0x13 四格验 STA 的地址与数据源（08-0B 的写 Rd 的那条是 LDI）；
;   0x20 那道值来自 0C 的 LD，走过 MemToReg mux 的 MemData 那一路——两个输入接反时
;     它会是地址 0x10 而不是数据 0x11；
;   0x14 那道值来自 16 的 ADD，走 MemToReg mux 的 ALUResult 那一路。
;
; 出错时的症状：0x10-0x13 全 0 → 写地址接了 Inst[15:12]；四格全 0x11 → 写数据 mux
;   取错口（STA 的数据源在 [11:8]，走 A 口）；0x20 = 0x10 → MemToReg mux 两极接反；
;   0x20 = 0x00 → RAM 的 DataOut 没接到 MEM/WB.MemData；0x14 = 0x00 → ADD 的结果没进寄存器。
;
; ROM 0x1B 之后是 0，译出来是 ADD R0,R0,R0（不写 RAM），所以程序跑过末尾会一直空转，
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
        STA R9, 0x20     ; RAM[0x20] = 0x11（走过 MemToReg mux 的 MemData 那一路）

        LDI R13, 3
        LDI R14, 4
        LDI R15, 0
        LDI R0, 0
        LDI R6, 0        ; 填充：把 11 / 12 与 16 的距离推到 k=4
        ADD R1, R13, R14 ; R1 = 7
        LDI R7, 0
        LDI R8, 0
        LDI R10, 0
        STA R1, 0x14     ; RAM[0x14] = 0x07（走过 MemToReg mux 的 ALUResult 那一路）
