export const clampTime = (time, duration) => Math.max(0, Math.min(Number.isFinite(time) ? time : 0, duration));
export function changeEvent(action, start, end, revision, resize = false) {
  if (action.clip_id) return {kind: 'audio', clip_id: action.clip_id, start, end, resize, revision};
  if (action.effectId === 'captions') return {kind: 'caption', index: action.index, start, end, revision};
  if (action.effectId === 'visual') return resize
    ? {kind: 'resize', scene_id: action.scene_id, duration: end - start, revision}
    : {kind: 'reorder', scene_id: action.scene_id, start, revision};
  return null;
}
export function timecode(time) {
  const value = Math.max(0, Number.isFinite(time) ? time : 0);
  const minutes = Math.floor(value / 60), seconds = Math.floor(value % 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(Math.floor((value % 1) * 100)).padStart(2, '0')}`;
}
// The timestamp at duration is past the final decoded frame. Keep paused seeks
// on the delivery video's 30 fps frame grid, including at the end of the video.
export function frameTime(time, duration, fps = 30) {
  const last = Math.max(0, Math.ceil(duration * fps) - 1) / fps;
  return clampTime(Math.round(clampTime(time, duration) * fps) / fps, last);
}
