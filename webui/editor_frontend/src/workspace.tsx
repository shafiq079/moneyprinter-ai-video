import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Timeline} from '@xzdarcy/react-timeline-editor';
import {clampTime, changeEvent, timecode} from './model.mjs';
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
      const update = () => {const t = next.currentTime + data.playbackOffset; setTime(t); setPlaying(!next.paused); timeline.current?.setTime(t);};
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
    observer.observe(document.querySelector('.st-key-editor_program') || document.body, {childList: true, subtree: true});
    return () => {observer.disconnect(); remove(); video.current = null;};
  }, []);
  function seek(value: number) {
    const target = clampTime(value, data.duration);
    if (video.current) video.current.currentTime = clampTime(target - data.playbackOffset, video.current.duration || data.duration);
    setTime(target); timeline.current?.setTime(target);
  }
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
  const labels = data.labels;
  const scale = data.extent > 90 ? 10 : data.extent > 30 ? 5 : 1;
  const dimensions = {scale, scaleWidth: Math.max(45, 80 * zoom), rowHeight: 46};
  return <section className="mpt-timeline" aria-label={labels.timeline}>
    <div className="timeline-toolbar">
      <div className="transport">
        <button aria-label={labels.start} title={labels.start} onClick={() => seek(0)} disabled={!connected}>|◀</button>
        <button className="play" aria-label={playing ? labels.pause : labels.play} onClick={toggle} disabled={!connected}>{playing ? 'Ⅱ' : '▶'}</button>
        <button aria-label={labels.frameBack} title={labels.frameBack} onClick={() => seek(time - 1 / 30)} disabled={!connected}>‹</button>
        <button aria-label={labels.frameNext} title={labels.frameNext} onClick={() => seek(time + 1 / 30)} disabled={!connected}>›</button>
        <output aria-live="off">{timecode(time)} <span>/ {timecode(data.duration)}</span></output>
      </div>
      <div className="timeline-tools">
        <span className="draft-badge">{data.captionDraft ? labels.draft : labels.saved}</span>
        <label>{labels.zoom}<input aria-label={labels.zoom} type="range" min="0.5" max="3" step="0.25" value={zoom}
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
        minScaleCount={Math.ceil(data.extent / scale) + 3} scaleSplitCount={scale === 1 ? 5 : 10} gridSnap={false} dragLine
        disableDrag={data.busy} onChange={setRows}
        getScaleRender={value => <span>{timecode(value).slice(0, 5)}</span>}
        getActionRender={(action: any) => <div className={`clip-content ${action.effectId} ${data.selected === action.id ? 'selected' : ''}`} title={action.label}>
          <span>{action.label}</span><small>{(action.end - action.start).toFixed(2)}s</small></div>}
        onClickActionOnly={(_, {action}) => select(action)}
        onCursorDrag={seek} onClickTimeArea={value => {seek(value); return true;}}
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

export default function(component: any) {
  const element = document.createElement('div');
  component.parentElement.appendChild(element);
  const root = createRoot(element);
  root.render(<Workspace component={component}/>);
  return () => root.unmount();
}
