import type { Flow } from "../types";

// Each flow mirrors a real client's WhatsApp-bot lead schema — the fields the
// bot collects (run.variables). Single-client CRM: FLOWS[0] is the active one.
export const FLOWS: Flow[] = [
  {
    id: "jpc",
    name: "Jain Pain Clinic",
    fields: [
      { key: "pain", label: "Pain / Complaint", type: "text" },
      { key: "appt_type", label: "Appointment Type", type: "enum", options: ["Clinic visit", "Online consultation", "Send MRI/X-Ray"] },
      { key: "appt_date", label: "Appointment Date", type: "date" },
      { key: "appt_time", label: "Appointment Time", type: "text" },
      { key: "consult_mode", label: "Consult Mode", type: "enum", options: ["", "Audio", "Video", "Counsellor", "Head of Dept"] },
      { key: "branch", label: "Branch", type: "enum", options: ["Gurugram", "New Delhi", "Faridabad"] },
      { key: "doctor", label: "Doctor", type: "text" },
      { key: "campaign", label: "Campaign", type: "text" },
      { key: "ad_id", label: "Ad ID", type: "text" },
      { key: "report_sent", label: "Report Sent", type: "enum", options: ["", "Yes", "No"] },
    ],
  },
];

export const ACTIVE_FLOW: Flow = FLOWS[0];
export const flowById = (id: string): Flow => FLOWS.find((f) => f.id === id) || FLOWS[0];
