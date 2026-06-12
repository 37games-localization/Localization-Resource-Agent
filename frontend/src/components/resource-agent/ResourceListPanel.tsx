import type { CandidateResource } from "./types";

type ResourceListPanelProps = {
  resources: CandidateResource[];
  selectedRecordId: string;
  resourceError: string;
  onSelect: (recordId: string) => void;
  onRefresh: () => void;
};

export function ResourceListPanel({ resources, selectedRecordId, resourceError, onSelect, onRefresh }: ResourceListPanelProps) {
  return (
    <section className="panel resource-list-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">资源列表</h2>
          <p className="meta">来自 Lark 简历招募表，共 {resources.length} 条</p>
        </div>
        <button className="button secondary" onClick={onRefresh} type="button">
          刷新
        </button>
      </div>
      {resourceError && <div className="next-box">{resourceError}</div>}
      <div className="resource-list">
        {resources.map((resource) => {
          const isSelected = resource.recordId === selectedRecordId;
          return (
            <article className={`resource-row ${isSelected ? "selected" : ""}`} key={resource.recordId}>
              <button className="resource-row-trigger" onClick={() => onSelect(isSelected ? "" : resource.recordId)} type="button">
                <div className="resource-row-main">
                  <strong>{resource.name || resource.nickname || resource.recordId}</strong>
                  <span>{resource.recordId}</span>
                </div>
                <div className="resource-row-meta">
                  <span>{resource.languagePair || "未填语言对"}</span>
                  <span>{resource.services || "未填服务"}</span>
                </div>
                <div className="resource-row-badges">
                  <span className="badge tone-info">{resource.tier || "未评级"}</span>
                  <span className="badge tone-success">{resource.status || "无状态"}</span>
                </div>
              </button>
              {isSelected && (
                <div className="resource-row-detail">
                  <dl>
                    <div>
                      <dt>邮箱</dt>
                      <dd>{resource.email || "未填"}</dd>
                    </div>
                    <div>
                      <dt>总分</dt>
                      <dd>{resource.score || "未评分"}</dd>
                    </div>
                    <div>
                      <dt>有效简历</dt>
                      <dd>{resource.validResume || "未判断"}</dd>
                    </div>
                    <div>
                      <dt>AI建议</dt>
                      <dd>{resource.aiSuggestion || "未生成"}</dd>
                    </div>
                  </dl>
                  <details>
                    <summary>评分依据摘要</summary>
                    <p>{resource.scoreBasis || "暂无评分依据。"}</p>
                  </details>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
