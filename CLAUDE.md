# CLAUDE.md

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. 一切都需要为最后产出的质量服务，所有设计保证最高质量

## 3. 详细思考，认真调研，设计先行

请在详细了解我们的代码和系统之后再动手，目前我们的系统是一个大型系统，请充分了解，复杂任务和实现在开始之前需要充分的调研，充分思考，编写指导文档。

## 4. 有记录化、工程化地进行工作

制定详细的系统化的体系来优化整个系统，完成一定阶段工作之后需要定期检查和思考目前的工作和状态，并整理当前文件，保持整体路径井井有条，更新说明文档（文档即工作状态），合理管理上下文（太长自行压缩），保证效率和高质量推进。

## 5.系统化的工作

确保进行的优化工作是设计充分，考虑全面的系统（可以被迁移和值得学习的程度）。

## 6. 多方面测试

既要有软件工程等里的规模化扫描和优化，也要有从真实用户角度的，对于运行中的系统的直接规模化测试和优化。

## 7. 核心目标
 
不断自主推进和优化目前的agent系统和前端到一个更完善/系统更健全/能力更强大的系统，确保提供高质量、功能均正常运行的信息门户前端服务。

## 8. 数据系统和整体设计说明

1.我们目前的agent系统由nl-sql agent和api-routing agent组成，其中nl-sql agent对于我们整理和清洗好的



