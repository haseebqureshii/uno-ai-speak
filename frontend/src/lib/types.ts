export interface ControlMessage {
  type: string;
  [key: string]: any;
}

export interface LessonSetup {
  client_id: string;
  target_language: string;
  home_language: string;
  proficiency_level: string;
  session_length_minutes: number;
  lockout_cooldown_minutes: number;
  provider: string;
  weak_lexicon: string[];
}