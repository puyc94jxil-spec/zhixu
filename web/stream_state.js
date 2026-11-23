/** 把 SSE 事件记到对应会话，避免切会话时串流。临时 delta 不能变成可信引用。 */
export function createState() {
  return { conversations: {}, activeId: null };
}

export function ensure(state, conversationId) {
  if (!state.conversations[conversationId]) {
    state.conversations[conversationId] = { messages: {}, requests: {} };
  }
  return state.conversations[conversationId];
}

export function applyEvent(state, conversationId, requestId, eventName, data) {
  const bucket = ensure(state, conversationId);
  const request = bucket.requests[requestId] || {
    requestId,
    conversationId,
    text: "",
    provisional: false,
    citations: [],
    status: "accepted",
    error: null,
  };
  if (eventName === "delta" && data && data.provisional === true && !data.redacted) {
    request.text += data.text || "";
    request.provisional = true;
    request.status = "streaming";
  }
  if (eventName === "citation" && data && data.verified === true) {
    request.citations.push(data);
  }
  if (eventName === "done") {
    request.status = data.status;
    request.provisional = false;
  }
  if (eventName === "error") {
    request.status = "failed";
    request.error = data;
    request.provisional = false;
  }
  bucket.requests[requestId] = request;
  return request;
}

export function visibleCitations(request) {
  if (!request || request.status !== "completed") return [];
  return (request.citations || []).filter((item) => item.verified === true);
}
