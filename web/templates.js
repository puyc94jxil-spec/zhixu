export const DOCUMENT_TEMPLATES = [
  { id: "summary", label: "总结文档", prompt: "请总结当前文档的要点。", needsDocument: true },
  { id: "data", label: "提取关键数据", prompt: "请提取当前文档中的关键数据。", needsDocument: true },
  { id: "risk", label: "梳理风险", prompt: "请梳理当前文档里的风险。", needsDocument: true },
  { id: "free", label: "自由提问", prompt: "", needsDocument: false },
];

export function templateState(files) {
  const ready = (files || []).some((file) => file.status === "ready" && file.enabled !== 0);
  return DOCUMENT_TEMPLATES.map((item) => ({
    ...item,
    enabled: item.needsDocument ? ready : true,
    reason: item.needsDocument && !ready ? "还没有就绪的文档，这个模板暂时不能用" : "",
  }));
}
