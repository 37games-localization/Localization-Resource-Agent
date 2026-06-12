import type { ConsoleTuning } from "./types";

type TuningPanelProps = {
  isOpen: boolean;
  tuning: ConsoleTuning;
  onToggle: () => void;
  onChange: <K extends keyof ConsoleTuning>(key: K, value: ConsoleTuning[K]) => void;
  onReset: () => void;
};

export function TuningPanel({ isOpen, tuning, onToggle, onChange, onReset }: TuningPanelProps) {
  return (
    <>
      <section className="console-design-bar">
        <button className="button secondary" onClick={onToggle} type="button">
          {isOpen ? "收起调试面板" : "打开调试面板"}
        </button>
        <p className="meta">
          调整只影响当前浏览器预览；确认后再固化到代码。左侧 {tuning.leftWidth}% / 日志 {tuning.eventPreviewLines} 行 /{" "}
          {tuning.density === "compact" ? "紧凑" : "舒展"}密度
        </p>
      </section>

      {isOpen && (
        <section className="panel console-tuning-panel">
          <div className="tuning-control">
            <label htmlFor="left-width">左侧列表宽度</label>
            <input
              id="left-width"
              max="58"
              min="32"
              onChange={(event) => onChange("leftWidth", Number(event.target.value))}
              type="range"
              value={tuning.leftWidth}
            />
            <span>{tuning.leftWidth}%</span>
          </div>
          <div className="tuning-control">
            <label htmlFor="event-lines">执行流折叠高度</label>
            <input
              id="event-lines"
              max="6"
              min="1"
              onChange={(event) => onChange("eventPreviewLines", Number(event.target.value))}
              type="range"
              value={tuning.eventPreviewLines}
            />
            <span>{tuning.eventPreviewLines} 行</span>
          </div>
          <div className="tuning-segment">
            <span>页面密度</span>
            <button className={tuning.density === "comfortable" ? "selected" : ""} onClick={() => onChange("density", "comfortable")} type="button">
              舒展
            </button>
            <button className={tuning.density === "compact" ? "selected" : ""} onClick={() => onChange("density", "compact")} type="button">
              紧凑
            </button>
          </div>
          <div className="tuning-segment">
            <span>确认摘要</span>
            <button className={tuning.checkpointMode === "inline" ? "selected" : ""} onClick={() => onChange("checkpointMode", "inline")} type="button">
              原位
            </button>
          </div>
          <label className="tuning-checkbox">
            <input checked={tuning.showRawPayload} onChange={(event) => onChange("showRawPayload", event.target.checked)} type="checkbox" />
            展开时显示 raw payload
          </label>
          <button className="button secondary" onClick={onReset} type="button">
            恢复默认
          </button>
        </section>
      )}
    </>
  );
}
