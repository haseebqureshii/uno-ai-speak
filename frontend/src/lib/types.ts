export type ProficiencyLevel = "A1" | "A2" | "B1" | "B2" | "C1";
export type Phase = "WARMUP" | "DRILL" | "ROLEPLAY" | "PAUSE" | "WRAPUP" | "LOCKED";

export interface LessonSetup {
  clientId: string;
  targetLanguage: string;
  homeLanguage: string;
  proficiencyLevel: ProficiencyLevel;
  sessionLengthMinutes: number;
  lockoutCooldownMinutes: number;
  weakLexicon?: string[];
}

export interface AssessmentScores {
  communicative_success: number;
  lexical_resource: number;
  grammatical_control: number;
  fluency: number;
}

export interface DetectedGap {
  phrase: string;
  issue: string;
  type: string;
}

export interface SessionAssessment {
  scenario_id: string;
  timestamp: string;
  scores: AssessmentScores;
  milestone_completed: boolean;
  target_lexicon_used: string[];
  missed_lexicon: string[];
  detected_gaps: DetectedGap[];
  completion_conditions_met?: string[];
  completion_conditions_total?: number;
  drift_strikes?: number;
}

export interface ControlMessage {
  type: string;
  source: string;
  reason?: string;
  target_state?: string;
  payload?: Record<string, unknown>;
}

export interface SessionState {
  phase: string;
  driftStrikes: number;
  isLockedOut: boolean;
  lockoutUntil: string | null;
  targetLanguage: string;
  proficiencyLevel: string;
}
