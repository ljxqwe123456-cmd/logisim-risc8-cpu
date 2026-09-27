; 冒险自测：间隔正好 2 条的 RAW —— 判据是前递优先级 2（MEM/WB 那一路，见 docs/datapath.md §4）。
; 验证时机：§8 第 6 步。两个前递 mux 接好即可通过，不需要 Hazard Unit、不需要分支、不需要 OUT。
;           全文没有一处会触发停顿，Hazard Unit 搭了没搭都不影响这一条。
;
; 为什么要有这一条：优先级 1（EX/MEM）有 hazard_k3.asm 的 ST 数据源与 square_lookup.asm 的
;   8 次 STA 兜着，优先级 2 却只有 hazard_k2branch.asm 与 hazard_branch.asm 在判，而那两条都
;   走分支、结果只落在 OUT 上。分支与 OUT 都还没接的第 6 步，这一级没有任何可看的判据。
;   （与 hazard_k2branch.asm 不是一回事：那条考分支操作数，本条考 store 与 ALU 的数据通路。）
;
; 结果全在 RAM 里，用 RAM 内容窗口读，不经 OUT：
;   0x40 = 0xA1   0x41 = 0xB2   0x42 = 0x2A   其余全 0x00
;
; 三格各考一处，每一处都是「写 Rd 的那条与读 Rd 的那条相隔 2 条」：
;   0x40：03 写 R1 → 05 的 STA 读，数据源在 A 口（Inst[11:8]）；
;   0x41：07 写 R2 → 09 的 ST  读，数据源在 B 口（Inst[7:4]）；
;   0x42：0C 的 ADD 写 R4 → 0E 的 STA 读，结果经 A 口送进 RAM。
;
; 出错时的症状：
;   三格都是 0x0F → 优先级 2 整级没接。0x0F 是那三个寄存器被覆盖之前的值：少了这一级，前递
;     mux 回落到寄存器堆，而 ID 读口当场读到的正是这个旧值（写 Rd 的那条此时刚进 EX，还没写回）。
;   三格都是 0x00 → 先查拍数（见下），排除了再看 store 通路本身（step5_smoke.asm 已验过一遍）。
;
; 跑够 20 拍后停时钟：最后一条（0x0E）的 STA 到第 18 拍才进 MEM 段，写落在第 19 个时钟沿。
; ROM 0x0F 之后是 0，即保留码 op=0000（空操作，不写 RAM），所以跑过末尾会一直空转，
; RAM 内容停在上面那张表上不动。

        LDI R5, 0x41     ; 09 的 ST 用的地址寄存器（00 写 → 09 读，k=9，走寄存器堆）
        LDI R4, 0x0F     ; 哨兵：优先级 2 缺失时 0E 读到的是它
        LDI R1, 0x0F     ; 哨兵
        LDI R1, 0xA1     ; 写 Rd 的那条 —— 05 的 STA 在 k=2 读它
        LDI R9, 0        ; 填充，把上面那条与 05 拉开到正好 k=2
        STA R1, 0x40     ; RAM[0x40] = 0xA1，数据源走 A 口
        LDI R2, 0x0F     ; 哨兵
        LDI R2, 0xB2     ; 写 Rd 的那条 —— 09 的 ST 在 k=2 读它
        LDI R9, 0        ; 填充
        ST  R2, [R5]     ; RAM[0x41] = 0xB2，数据源走 B 口
        LDI R3, 0x15     ; ADD 的源，0C 在 k=2 读它
        LDI R9, 0        ; 填充
        ADD R4, R3, R3   ; R4 = 0x2A
        LDI R9, 0        ; 填充，把 R4 与 0E 拉开到正好 k=2
        STA R4, 0x42     ; RAM[0x42] = 0x2A，ALU 结果经 A 口
