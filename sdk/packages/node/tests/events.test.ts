import { describe, expect, it } from "vitest";
import {
  answerFrame,
  cancelFrame,
  createCallFrame,
  EventType,
  isTerminal,
  parseEvent,
} from "../src/index.js";

describe("command frames", () => {
  it("uses Nest websocket envelope and camelCase data", () => {
    expect(createCallFrame("+821012345678", "agent-1", "hi", { src: "test" }, "r1")).toEqual({
      event: "createCall",
      data: {
        to: "+821012345678",
        agentId: "agent-1",
        prompt: "hi",
        metadata: { src: "test" },
        requestId: "r1",
      },
    });
  });

  it("omits optional fields", () => {
    expect(createCallFrame("+821012345678", "agent-1")).toEqual({
      event: "createCall",
      data: { to: "+821012345678", agentId: "agent-1", prompt: "" },
    });
    expect(answerFrame("yo", "m1")).toEqual({
      event: "answer",
      data: { text: "yo", messageId: "m1" },
    });
    expect(cancelFrame()).toEqual({ event: "cancel", data: {} });
  });
});

describe("events", () => {
  it("parses flat user turn frames", () => {
    const event = parseEvent({
      type: "user.turn",
      version: "1.0",
      sessionId: "s1",
      callId: "c1",
      turnIndex: 2,
      text: "hey",
      timestamp: "t",
    });

    expect(event.type).toBe(EventType.UserTurn);
    expect(event.turnIndex).toBe(2);
    expect(event.text).toBe("hey");
    expect(event.sessionId).toBe("s1");
    expect(event.callId).toBe("c1");
  });

  it("parses error frames with request id and question", () => {
    const event = parseEvent({
      type: "error",
      version: "1.0",
      code: "callRejected",
      message: "Call rejected",
      requestId: "r1",
      question: "why?",
    });

    expect(event.code).toBe("callRejected");
    expect(event.requestId).toBe("r1");
    expect(event.question).toBe("why?");
  });

  it("parses no-answer terminal frames with failure reason", () => {
    const event = parseEvent({
      type: "call.noAnswer",
      version: "1.0",
      sessionId: "s1",
      callId: "c1",
      status: "noAnswer",
      failureReason: "timeout",
      timestamp: "t",
    });

    expect(event.type).toBe(EventType.CallNoAnswer);
    expect(event.status).toBe("noAnswer");
    expect(event.failureReason).toBe("timeout");
    expect(isTerminal(event)).toBe(true);
  });

  it("detects terminal events including cancelled status", () => {
    expect(
      isTerminal(
        parseEvent({
          type: "call.completed",
          version: "1.0",
          sessionId: "s1",
          callId: "c1",
          status: "completed",
          timestamp: "t",
        }),
      ),
    ).toBe(true);
    expect(
      isTerminal(
        parseEvent({
          type: "call.statusChanged",
          version: "1.0",
          sessionId: "s1",
          callId: "c1",
          status: "cancelled",
          previousStatus: "inProgress",
          timestamp: "t",
        }),
      ),
    ).toBe(true);
  });
});
