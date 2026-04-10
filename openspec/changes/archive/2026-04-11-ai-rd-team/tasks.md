## 1. 基础设施

- [x] 1.1 创建 `ai-rd-team/rd-team/shared-rd-resources/tech-profiles/tech-profiles.json` 技术栈画像配置（5 个画像：generic / go-kratos-web / go-kratos-api / python-web 占位 / node-web 占位）
- [x] 1.2 创建 `ai-rd-team/ARCHITECTURE.md` 包级架构说明文档
- [x] 1.3 创建 `ai-rd-team/rd-team/SKILL.md` Skill 入口定义文件

## 2. Agent Prompt 文件

- [x] 2.1 创建 `ai-rd-team/rd-team/agents/analyst.md` 需求分析师 Agent prompt
- [x] 2.2 创建 `ai-rd-team/rd-team/agents/architect.md` 架构设计师 Agent prompt
- [x] 2.3 创建 `ai-rd-team/rd-team/agents/backend-dev.md` 后端开发工程师 Agent prompt（含 Kratos 分层约束 + TDD）
- [x] 2.4 创建 `ai-rd-team/rd-team/agents/frontend-dev.md` 前端开发工程师 Agent prompt（Vue 3 + TypeScript）
- [x] 2.5 创建 `ai-rd-team/rd-team/agents/code-reviewer.md` 代码检视员 Agent prompt（含自主退回决策权）
- [x] 2.6 创建 `ai-rd-team/rd-team/agents/tester.md` 测试工程师 Agent prompt（含自主报 bug 决策权）

## 3. 协调者

- [x] 3.1 创建 `ai-rd-team/rd-team/commands/rd-team.md` 协调者完整 prompt（500+ 行，含画像解析/模式判定/团队创建/Agent 派发/并行编排/心跳/异常恢复/迭代回退/完成清理/视觉系统）

## 4. 验证

- [x] 4.1 验证包结构完整性（所有文件存在、路径引用正确）
- [x] 4.2 验证 tech-profiles.json 格式正确、画像继承关系正确
- [x] 4.3 审查全部文件质量（prompt 结构一致性、术语一致性）
