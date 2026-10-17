import type { AgAiEvent, AgLlmAdapter, AgLlmRequest, AgLlmResponse } from "ag-studio";

// Studio runs its own agent loop in the browser and asks for one model turn at a time. Each turn goes to
// Countersign's server, which holds the model keys, so nothing secret is ever in this page.
export function serverAdapter(token: () => string | null): AgLlmAdapter {
  return {
    executeTurn(request: AgLlmRequest, options) {
      const response: Promise<AgLlmResponse> = fetch("/api/studio/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token() ? { "X-Owner-Token": token()! } : {}) },
        body: JSON.stringify({ input: request.input, instructions: request.instructions, tools: request.tools, toolChoice: request.toolChoice }),
        signal: options?.signal,
      }).then(async (r) => {
        if (!r.ok) {
          const detail = await r.json().then((j) => j.detail).catch(() => "");
          throw new Error(typeof detail === "string" && detail ? detail : `The assistant could not answer (${r.status}).`);
        }
        const body = await r.json();
        return { id: body.id, createdAt: Date.now(), status: "completed", output: body.output, model: body.model } as AgLlmResponse;
      });
      response.catch(() => undefined);   // a rejection is reported through `complete`; keep the stream from raising it twice

      async function* stream(): AsyncGenerator<AgAiEvent> {
        const done = await response;
        for (const item of done.output) {
          if (item.type !== "message") continue;
          for (const part of item.content) {
            if (part.type !== "text") continue;
            yield { type: "TEXT_MESSAGE_START", messageId: item.id, role: "assistant" };
            yield { type: "TEXT_MESSAGE_CONTENT", messageId: item.id, delta: part.text };
            yield { type: "TEXT_MESSAGE_END", messageId: item.id };
          }
        }
      }
      return { stream: stream(), complete: response };
    },
  };
}
