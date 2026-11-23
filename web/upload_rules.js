const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 5;

export function uploadBlockReason(existing, incoming) {
  const name = String(incoming.name || "");
  const suffix = name.slice(name.lastIndexOf(".")).toLowerCase();
  if (![".txt", ".md", ".pdf", ".docx"].includes(suffix)) {
    return "只接受 TXT、MD、PDF、DOCX";
  }
  if (incoming.size <= 0) {
    return "空文件不能解析";
  }
  if (incoming.size > MAX_FILE_BYTES) {
    return "单个文件不能超过 20MB";
  }
  const active = (existing || []).filter((file) => file.status !== "failed");
  if (active.length >= MAX_FILES) {
    return "每个会话最多 5 个文件，请先处理已有文件";
  }
  return "";
}

export function fileStatusLabel(status) {
  return {
    uploaded: "已上传",
    scanning: "安全检查",
    parsing: "解析中",
    indexing: "索引中",
    ready: "就绪",
    failed: "失败",
  }[status] || status;
}
