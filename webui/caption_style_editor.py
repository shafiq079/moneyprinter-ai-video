"""Caption style forms use the same bounded draft queue as text and timing edits."""
from pathlib import Path

import streamlit as st

from app.utils import utils


def render(draft, params, revision, task_id, busy, queue, tr, index=None):
    scopes = {'all': tr('All Captions'), 'cue': tr('Selected Caption')}
    with st.expander(tr('Caption Appearance')):
        scope = st.selectbox(tr('Caption Style Scope'), ['all', 'cue'] if index is not None else ['all'],
                            format_func=lambda value, labels=scopes: labels[value],
                            key=f'caption_style_scope_{task_id}', disabled=busy or index is None)
        style = {**params.model_dump(), **draft.get('style', {})}
        if scope == 'cue' and index is not None:
            style.update(draft['cues'][index].get('style', {}))
        suffix = f'{task_id}_{revision}_{scope}_{index}'
        with st.form(f'caption_appearance_{suffix}'):
            fonts = sorted(p.name for p in Path(utils.font_dir()).iterdir() if p.suffix.lower() in {'.ttf', '.ttc', '.otf'} and not p.name.startswith('.'))
            font = style.get('font_name')
            font = st.selectbox(tr('Font'), fonts, index=fonts.index(font) if font in fonts else 0)
            size = st.number_input(tr('Font Size'), 1, 200, max(1, min(200, int(style['font_size']))))
            foreground = st.color_picker(tr('Font Color'), style.get('text_fore_color') or '#FFFFFF')
            background = st.checkbox(tr('Enable Subtitle Background'), value=bool(style['text_background_color']))
            background_color = st.color_picker(tr('Subtitle Background Color'), style['text_background_color'] if isinstance(style['text_background_color'], str) else '#000000')
            rounded = st.checkbox(tr('Rounded Subtitle Background'), value=bool(style.get('rounded_subtitle_background')))
            stroke = st.color_picker(tr('Stroke Color'), style.get('stroke_color') or '#000000')
            width = st.number_input(tr('Stroke Width'), 0.0, 10.0, float(style.get('stroke_width') or 0), step=.5)
            positions = ['top', 'center', 'bottom', 'two_thirds_bottom', 'custom']
            position = st.selectbox(tr('Position'), positions, index=positions.index(style['subtitle_position']) if style['subtitle_position'] in positions else 2)
            custom = st.number_input(tr('Custom Position (% from top)'), 0.0, 100.0, float(style.get('custom_position', 70)))
            animation = st.selectbox(tr('Subtitle Animation'), ['none', 'pop_spring'], index=1 if style.get('subtitle_animation') == 'pop_spring' else 0)
            save = st.form_submit_button(tr('Save Caption Style'), disabled=busy)
        if save:
            queue('style', index=index, scope=scope, style={'font_name': font, 'font_size': size,
                'text_fore_color': foreground, 'text_background_color': background_color if background else False,
                'rounded_subtitle_background': rounded, 'stroke_color': stroke, 'stroke_width': width,
                'subtitle_position': position, 'custom_position': custom, 'subtitle_animation': animation})
        if scope == 'cue' and index is not None and st.button(tr('Reset Caption Style'), key=f'caption_style_reset_{suffix}', disabled=busy):
            queue('style', index=index, scope='cue', style={})
        st.caption(tr('Caption Style Preview Help'))
    if index is not None:
        selection = st.session_state.get(f'caption_selection_{task_id}_{revision}_{index}', {})
        with st.expander(tr('Selected Text Color'), expanded=bool(selection)):
            cue = draft['cues'][index]
            # Indexed choices identify repeated words and Unicode characters without
            # guessing which occurrence the user meant. End is exclusive.
            with st.form(f'caption_color_range_{suffix}'):
                start = st.number_input(tr('Text Selection Start'), 0, len(cue['text']) - 1, selection.get('start', 0))
                end = st.number_input(tr('Text Selection End'), 1, len(cue['text']), selection.get('end', len(cue['text'])))
                st.caption(cue['text'][start:end])
                color = st.color_picker(tr('Font Color'), '#FFFF00')
                save = st.form_submit_button(tr('Apply Selected Text Color'), disabled=busy)
                clear = st.form_submit_button(tr('Clear Text Colors'), disabled=busy)
            if save:
                spans = [span for span in cue.get('spans', []) if span['end'] <= start or span['start'] >= end]
                spans.append({'start': start, 'end': end, 'color': color})
                queue('spans', index=index, spans=sorted(spans, key=lambda span: span['start']))
            if clear:
                queue('spans', index=index, spans=[])
