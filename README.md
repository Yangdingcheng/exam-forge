# ExamForge · 智能组卷工作台

老师出卷最耗时的不是找题，是**配卷**：题型凑数、总分凑整、难度成梯度、知识点别漏。
ExamForge 把"配平"交给算法：你定一份**组卷蓝图**（题型配额 / 分值 / 难度分布 / 知识点覆盖），
它从你自己的本地题库里选题、配平、排版，产出可打印的试卷、参考答案和一份诚实的组卷报告。

- **本地运行，零依赖**：纯 Python 标准库，题库就是一个 JSON 文件，不上传、不注册、不要会员；
- **蓝图驱动**：先定卷子长什么样，再让引擎配题——不是随机抽题碰运气；
- **可复现**：题库 + 蓝图 + 种子相同，出的卷必然相同，教研组复核有据可查；
- **诚实报告**：配不平时明确告诉你哪项没达标（题库不足、覆盖缺口），不假装完美；
- **四件套产出**：试卷 Markdown、可打印 HTML（A4 + 答题卡）、参考答案、组卷清单 manifest。

设计说明见 [DESIGN.md](DESIGN.md)。与同系列 [LessonForge 教案工作台](https://github.com/Yangdingcheng/lesson-forge) 互补：一个管"怎么教"，一个管"怎么测"。

## 快速开始

```bash
python main.py demo        # 用自带示例题库一键出卷到 out/
python main.py validate --bank bank.sample.json
python main.py build --bank 你的题库.json --blueprint 你的蓝图.json --out out/
python tests.py            # 跑测试
```

`demo` 使用自带的七年级数学示例题库（42 道自编示例题）与蓝图，产出在 `out/`：
`paper.md`、`paper.html`（浏览器打开即可打印）、`answers.md`、`manifest.json`。

## 题库格式

```json
{
  "id": "num-01", "type": "choice",
  "stem": "-3 的相反数是（　）",
  "options": ["-3", "3", "1/3", "-1/3"],
  "answer": "B", "analysis": "只有符号不同的两数互为相反数。",
  "knowledge": ["有理数"], "difficulty": 1
}
```

`type` 取 `choice`（选择）/ `fill`（填空）/ `judge`（判断，答案 √ 或 ×）/ `solve`（解答）；
`difficulty` 为 1–5，组卷时映射为易（1–2）/ 中（3）/ 难（4–5）三档。
先用 `validate` 给题库体检：查重题、缺答案、难度越界都会被揪出来。

## 蓝图长什么样

见 `blueprint.sample.json`：题型与分值（示例卷正好 100 分）、难度分布目标
（易 45% / 中 35% / 难 20%）、必覆盖知识点及每点最少题数、随机种子、排除题目 ID
（比如上次月考用过的题，这次避开）。

## 选题算法（一句话版）

硬配额先行 → 贪心逐题配平（知识点覆盖增益 + 难度档缺口 + 种子抖动）→
同题型交换改进，直到难度分布与覆盖缺口收敛。细节见 DESIGN.md。

## 注意

- 示例题库为演示用的自编题，正式使用请换成自己的题库，并逐题核对答案；
- 工具只做配平与排版，不联网、不抓题；最终试卷请老师过目后再印发。

MIT License
