type WorkbenchTopbarProps = {
  currentRun: string;
  latestSummary: string;
};

export function WorkbenchTopbar({ currentRun, latestSummary }: WorkbenchTopbarProps) {
  return (
    <section className="workbench-topbar">
      <div>
        <p className="eyebrow">Resource Agent Workspace</p>
        <h1>资源管理 Agent 工作台</h1>
        <p className="subtitle">
          左侧直接读取 Lark 简历招募表；右侧通过对话调用现有 Agent 脚本，执行过程默认折叠，人工确认结果以气泡返回。
        </p>
      </div>
      <div className="console-status-card">
        <span>当前 Run</span>
        <strong>{currentRun}</strong>
        <p>{latestSummary}</p>
      </div>
    </section>
  );
}
