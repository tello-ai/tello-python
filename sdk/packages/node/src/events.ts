import { EventType, type TelloEvent } from "./types.js";

const terminalTypes = new Set<string>([
  EventType.CallCompleted,
  EventType.CallNoAnswer,
  EventType.CallFailed,
]);

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function parseEvent(frame: Record<string, unknown>): TelloEvent {
  const type = stringValue(frame.type);

  if (type === EventType.Error) {
    return {
      type,
      version: stringValue(frame.version),
      sessionId: "",
      callId: "",
      timestamp: "",
      code: stringValue(frame.code),
      message: stringValue(frame.message),
      requestId: typeof frame.requestId === "string" ? frame.requestId : undefined,
      question: typeof frame.question === "string" ? frame.question : undefined,
      raw: frame,
    };
  }

  const event: TelloEvent = {
    type,
    version: stringValue(frame.version),
    sessionId: stringValue(frame.sessionId),
    callId: stringValue(frame.callId),
    timestamp: stringValue(frame.timestamp),
    raw: frame,
  };

  if (type === EventType.UserTurn || type === EventType.AgentTurn) {
    event.turnIndex = numberValue(frame.turnIndex);
    event.text = stringValue(frame.text);
  } else if (type === EventType.CallStatusChanged) {
    event.status = stringValue(frame.status);
    event.previousStatus = stringValue(frame.previousStatus);
  } else if (terminalTypes.has(type)) {
    event.status = stringValue(frame.status);
    event.failureReason = typeof frame.failureReason === "string" ? frame.failureReason : undefined;
  }

  return event;
}

export function isTerminal(event: TelloEvent): boolean {
  return terminalTypes.has(event.type) || (event.type === EventType.CallStatusChanged && event.status === "cancelled");
}
