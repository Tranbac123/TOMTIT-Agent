Planner tạo step
↓
PlanValidator kiểm tra step hợp lệ
↓
ToolExecutor lấy ToolSpec
↓
ArgResolver resolve args
↓
Check allowed_args / required_args
↓
Validate args bằng args_schema nếu có
↓
PolicyEngine.check(tool, args, state)
↓
ApprovalGate.check(tool, args, state)
↓
Execute tool.fn(state=state, \*\*args)
↓
Validate ToolResult
↓
Update state.last_result
↓
Add Observation
↓
Return ToolResult
