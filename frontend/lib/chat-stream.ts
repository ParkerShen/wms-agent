export type ChatStreamEvent =
  | { type: "delta"; text: string }
  | { type: "done" }
  | { type: "error"; message: string };

export type ChatStreamCallbacks = {
  onDelta: (text: string) => void;
};

/**
 * Read the backend's POST-based SSE protocol incrementally.
 * A text decoder and carry buffer preserve UTF-8 characters and SSE frames when
 * either is split across arbitrary network chunks.
 */
export async function streamChat(
  message: string,
  signal: AbortSignal,
  callbacks: ChatStreamCallbacks,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(errorBody?.detail ?? "聊天请求失败，请稍后重试。");
  }

  if (!response.body) {
    throw new Error("浏览器没有收到流式响应，请重试。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;

  const handleFrame = (frame: string) => {
    const data = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data) return;

    let event: ChatStreamEvent;
    try {
      event = JSON.parse(data) as ChatStreamEvent;
    } catch {
      throw new Error("聊天服务返回了无法识别的数据。");
    }

    if (event.type === "delta" && typeof event.text === "string") {
      callbacks.onDelta(event.text);
    } else if (event.type === "done") {
      completed = true;
    } else if (event.type === "error" && typeof event.message === "string") {
      throw new Error(event.message);
    } else {
      throw new Error("聊天服务返回了未知事件。");
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) handleFrame(frame);
    }

    buffer += decoder.decode();
    if (buffer.trim()) handleFrame(buffer);
    if (!completed) throw new Error("回答流意外结束，请重试。");
  } finally {
    if (!completed || signal.aborted) {
      await reader.cancel().catch(() => undefined);
    }
    reader.releaseLock();
  }
}
