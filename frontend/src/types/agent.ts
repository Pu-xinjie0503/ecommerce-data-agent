/**
 * 智能体类型定义
 * 定义问数智能体前端使用的 SSE 事件、流程步骤和聊天消息类型
 */
export type ProgressStatus = "running" | "success" | "error" | "blocked" | "need_clarification";

export type ClarificationPayload = {
  need_clarification?: boolean;
  status?: string;
  clarification_type?: string | null;
  clarification_question?: string | null;
  clarification_options?: string[];
};

export type ProgressEvent = {
  type: "progress";
  step: string;
  status: ProgressStatus;
};

export type ResultEvent = {
  type: "result";
  data: unknown;
};

export type ClarificationEvent = {
  type: "clarification";
  data: ClarificationPayload;
};

export type FinalEvent = {
  type: "final";
  request_id: string;
  success: boolean;
  status?: string;
  need_clarification?: boolean;
  clarification_type?: string | null;
  clarification_question?: string | null;
  clarification_options?: string[];
  sql?: string | null;
  result?: unknown;
  error_type?: string | null;
  error_message?: string | null;
  recoverable?: boolean;
  suggested_action?: string | null;
  warning_type?: string | null;
  warning_message?: string | null;
  missing_values?: string[] | null;
  matched_values?: string[] | null;
  trace_path?: string;
};

export type ErrorEvent = {
  type: "error";
  message: string;
};

export type AgentEvent = ProgressEvent | ResultEvent | ClarificationEvent | FinalEvent | ErrorEvent;

export type StepState = {
  step: string;
  status: ProgressStatus;
  updatedAt: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  steps?: StepState[];
  result?: unknown;
  clarification?: ClarificationPayload;
  error?: string;
  warning?: string;
};
