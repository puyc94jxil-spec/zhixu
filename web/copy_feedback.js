/** 复制结果只返回给人看的短句。真正写入剪贴板仍由浏览器完成。 */

export function copyFeedback(ok) {
  return ok ? "已复制" : "复制失败，请手动选择文字";
}
