/**
 * Detection overlay boundary. visual_event.v1 carries NO bounding box today (only
 * category, count, confidence, snapshot_ref), so there is nothing to draw and no box is
 * ever fabricated. When the contract gains normalized boxes, map them to DetectionBox.
 */
export interface DetectionBox {
  eventId: string;
  /** Normalized 0..1 coordinates relative to the video frame. */
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  confidence: number;
  timestamp: string;
}
