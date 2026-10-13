import { describe, expect, it, vi } from "vitest";

import { streamChat } from "@/lib/chat-stream";

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("streamChat", () => {
  it("parses split SSE frames and preserves unicode deltas", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        'data: {"type":"delta","text":"库存',
        '可用42件。"}\n\ndata: {"type":"done"}\n\n',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onDelta = vi.fn();

    await streamChat("查库存", new AbortController().signal, { onDelta });

    expect(onDelta.mock.calls).toEqual([["库存可用42件。"]]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chat",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("reports safe stream errors and rejects missing terminal events", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse(['data: {"type":"error","message":"请求失败"}\n\n']),
      ),
    );
    await expect(
      streamChat("查库存", new AbortController().signal, { onDelta: vi.fn() }),
    ).rejects.toThrow("请求失败");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse(['data: {"type":"delta","text":"部分内容"}\n\n']),
      ),
    );
    await expect(
      streamChat("查库存", new AbortController().signal, { onDelta: vi.fn() }),
    ).rejects.toThrow("回答流意外结束");
  });
});
