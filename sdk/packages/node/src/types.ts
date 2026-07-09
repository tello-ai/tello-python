export const PROTOCOL_VERSION = "1.0";

export const EventType = {
  UserTurn: "user.turn",
  AgentTurn: "agent.turn",
  CallStatusChanged: "call.statusChanged",
  CallCompleted: "call.completed",
  CallNoAnswer: "call.noAnswer",
  CallFailed: "call.failed",
  Error: "error",
  Disconnected: "disconnected",
} as const;

export type EventTypeValue = (typeof EventType)[keyof typeof EventType];

export type TelloEvent = {
  type: string;
  version: string;
  sessionId: string;
  callId: string;
  timestamp: string;
  raw: Record<string, unknown>;
  turnIndex?: number;
  text?: string;
  status?: string;
  previousStatus?: string;
  failureReason?: string;
  code?: string;
  message?: string;
  requestId?: string;
  question?: string;
};
