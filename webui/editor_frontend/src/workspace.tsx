import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Timeline} from '@xzdarcy/react-timeline-editor';
import {clampTime, changeEvent, timecode, frameTime} from './model.mjs';
import '@xzdarcy/react-timeline-editor/dist/react-timeline-editor.css';
import './workspace.css';

function Workspace({component}: {component: any}) {
  const {data, setTriggerValue} = component;
  const timeline = useRef<any>(null);
  const [rows, setRows] = useState(data.rows);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(() => Number(sessionStorage.getItem('mpt-editor-zoom') || 1));
  const [connected, setConnected] = useState(false);
  const [notice, setNotice] = useState('');
  const video = useRef<HTMLVideoElement | null>(null);
  const clock = useRef(0);
  const latest = useRef(data); latest.current = data;
  const seeking = useRef(false);
  const textSelection = useRef<any>(null);
  useEffect(() => setRows(data.rows), [data]);
  // The native Streamlit player owns authenticated task-media serving. The
  // documented v2 DOM bridge connects only to our explicitly keyed container.
  useEffect(() => {
    let remove = () => {};
    function connect() {
      const next = document.querySelector<HTMLVideoElement>('.st-key-editor_program video');
      if (next === video.current) return;
      remove(); video.current = next; setConnected(!!next);
      if (!next) return;
      const update = () => {const t = next.currentTime + latest.current.playbackOffset; if (seeking.current) return; setTime(t); setPlaying(!next.paused); timeline.current?.setTime(t);};
      const animate = () => {update(); if (!next.paused) clock.current = requestAnimationFrame(animate);};
      const play = () => {cancelAnimationFrame(clock.current); animate();};
      ['timeupdate', 'seeked', 'pause', 'ended', 'loadedmetadata'].forEach(e => next.addEventListener(e, update));
      next.addEventListener('play', play); update();
      remove = () => {
        cancelAnimationFrame(clock.current);
        ['timeupdate', 'seeked', 'pause', 'ended', 'loadedmetadata'].forEach(e => next.removeEventListener(e, update));
        next.removeEventListener('play', play);
      };
    }
    connect();
    const observer = new MutationObserver(connect);
    observer.observe(document.body, {childList: true, subtree: true});
    return () => {observer.disconnect(); remove(); video.current = null;};
  }, []);
  function seek(value: number) {
    const target = frameTime(value, data.duration, data.fps);
    if (video.current) {
      const player = video.current;
      player.pause();
      player.currentTime = clampTime(target - data.playbackOffset, player.duration || data.duration);
    }
    setTime(target); timeline.current?.setTime(target);
  }
  useEffect(() => { if (data.seekToken) seek(data.seekTime || 0); }, [data.seekToken]);
  const step = (direction: number) => {
    const current = video.current ? video.current.currentTime + data.playbackOffset : time;
    seek((Math.round(current * data.fps) + direction) / data.fps);
  };
  const send = (event: any) => {
    if (!event) return;
    video.current?.pause();
    setTriggerValue('event', {...event, nonce: crypto.randomUUID()});
  };
  function select(action: any) {
    seek(action.start);
    send({kind: 'select', target: action.id, revision: data.revision});
  }
  async function toggle() {
    if (!video.current) return;
    if (!video.current.paused) video.current.pause();
    else {try {await video.current.play(); setNotice('');} catch {setNotice(data.labels.playError);}}
  }
  function captureText() {
    const current = latest.current;
    const editor = Array.from(document.querySelectorAll<HTMLTextAreaElement>('.st-key-editor_inspector textarea'))
      .find(element => element.getAttribute('aria-label') === current.labels.captionText);
    if (!editor || editor.selectionStart === editor.selectionEnd) return;
    textSelection.current = {kind: 'text_selection', index: current.captionIndex,
      start: Array.from(editor.value.slice(0, editor.selectionStart)).length,
      end: Array.from(editor.value.slice(0, editor.selectionEnd)).length,
      text: editor.value, revision: current.revision};
  }
  useEffect(() => {
    document.addEventListener('selectionchange', captureText);
    return () => document.removeEventListener('selectionchange', captureText);
  }, []);
  function selectText() {
    captureText();
    const selection = textSelection.current;
    if (!selection || selection.revision !== data.revision || selection.index !== data.captionIndex) {
      setNotice(data.labels.textColor); return;
    }
    send(selection);
  }
  const labels = data.labels;
  const scale = zoom >= 10 ? 1 : data.extent > 90 ? 10 : data.extent > 30 ? 5 : 1;
  const dimensions = {scale, scaleWidth: Math.max(45, 80 * zoom), rowHeight: 46};
  return <section className="mpt-timeline" aria-label={labels.timeline}>
    <div className="timeline-toolbar">
      <div className="transport">
        <button aria-label={labels.start} title={labels.start} onClick={() => seek(0)} disabled={!connected}>|◀</button>
        <button className="play" aria-label={playing ? labels.pause : labels.play} onClick={toggle} disabled={!connected}>{playing ? 'Ⅱ' : '▶'}</button>
        <button aria-label={labels.frameBack} title={labels.frameBack} onClick={() => step(-1)} disabled={!connected}>‹</button>
        <button aria-label={labels.frameNext} title={labels.frameNext} onClick={() => step(1)} disabled={!connected}>›</button>
        <output aria-live="off">{timecode(time)} <span>/ {timecode(data.duration)}</span></output>
      </div>
      <div className="timeline-tools">
        <button onMouseDown={event => {captureText(); event.preventDefault();}} onClick={selectText} disabled={data.busy || !data.captionDraft}>{labels.textColor}</button>
        <span className="draft-badge">{data.captionDraft ? labels.draft : labels.saved}</span>
        <label>{labels.zoom}<input aria-label={labels.zoom} type="range" min="0.5" max="30" step="0.25" value={zoom}
          onChange={e => {setZoom(Number(e.target.value)); sessionStorage.setItem('mpt-editor-zoom', e.target.value);}} /></label>
      </div>
    </div>
    {notice && <p role="status">{notice}</p>}
    <div className="timeline-grid">
      <div className="track-labels"><div className="track-ruler">{labels.tracks}</div>
        {data.rows.map((row: any) => <div key={row.id} className={`track-label ${row.id}`}><b>{row.id === 'visual' ? 'V1' : row.id === 'captions' ? 'T1' : row.id === 'music' ? 'A2' : 'A1'}</b><span>{labels[row.id]}</span></div>)}
      </div>
      <Timeline ref={timeline} editorData={rows} effects={{visual: {id: 'visual'}, narration: {id: 'narration'}, captions: {id: 'captions'}, music: {id: 'music'}}}
        {...dimensions} style={{width: '100%', height: data.rows.length * 46 + 34}}
        minScaleCount={Math.ceil(data.extent / scale) + 3} scaleSplitCount={zoom >= 10 ? data.fps : scale === 1 ? 5 : 10} gridSnap={false} dragLine
        disableDrag={data.busy} onChange={setRows}
        getScaleRender={value => <span>{zoom >= 10 ? timecode(value) : timecode(value).slice(0, 5)}</span>}
        getActionRender={(action: any) => <div className={`clip-content ${action.effectId} ${data.selected === action.id ? 'selected' : ''}`} title={action.label}>
          <span>{action.label}</span><small>{(action.end - action.start).toFixed(2)}s</small></div>}
        onClickActionOnly={(_, {action}) => select(action)}
        onCursorDragStart={() => {seeking.current = true; video.current?.pause();}}
        onCursorDrag={seek} onCursorDragEnd={value => {seeking.current = false; seek(value);}} onClickTimeArea={value => {seek(value); return true;}}
        onActionResizing={({action, start, end, dir}) => {
          if (action.effectId === 'visual' && dir === 'left') return false;
          return end - start >= 0.033 && start >= 0 && end <= data.extent;
        }}
        onActionMoveEnd={({action, start, end}) => send(changeEvent(action, start, end, data.revision))}
        onActionResizeEnd={({action, start, end}) => send(changeEvent(action, start, end, data.revision, true))}
      />
    </div>
    <footer><span className="selection-indicator">●</span>{labels.hint}<span className="powered">React Timeline Editor · MIT</span></footer>
  </section>;
}

// Streamlit calls the renderer again for data updates on the same host. Keep
// exactly one React root per host; older cleanup callbacks cannot remove it.
const mounts = new WeakMap<Element, {element: HTMLDivElement, root: ReturnType<typeof createRoot>, token: object}>();
export default function(component: any) {
  const host = component.parentElement;
  let mount = mounts.get(host);
  if (!mount) {
    const element = document.createElement('div');
    element.dataset.mptEditorRoot = 'true';
    host.appendChild(element);
    mount = {element, root: createRoot(element), token: {}};
    mounts.set(host, mount);
  }
  const token = {}; mount.token = token;
  mount.root.render(<Workspace component={component}/>);
  return () => {
    // Cleanup can be invoked for an obsolete render after the next update.
    if (mounts.get(host)?.token !== token) return;
    mount.root.unmount(); mount.element.remove(); mounts.delete(host);
  };
}
