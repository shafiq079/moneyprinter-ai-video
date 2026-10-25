export const clampTime = (time, duration) => Math.max(0, Math.min(Number.isFinite(time) ? time : 0, duration));
export function changeEvent(action, start, end, revision, resize = false) {
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
