# -*- coding: utf-8 -*-
"""AI call analysis: recording -> speech-to-text -> AI review (summary, interest, officer score).

Switch on/off in Settings. Only connected calls with a recording, at least N seconds long, from the
last few days are analysed, newest first, up to a daily limit (keeps the API bill predictable).
Speech-to-text: OpenAI transcription API. Review: Anthropic Claude or OpenAI chat (your choice)."""
import base64
import json
import logging
import re
import time

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

P = 'custom_leads_19.ai_'
STT_URL = 'https://api.openai.com/v1/audio/transcriptions'
OPENAI_CHAT_URL = 'https://api.openai.com/v1/chat/completions'
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
GROQ_STT_URL = 'https://api.groq.com/openai/v1/audio/transcriptions'
GROQ_CHAT_URL = 'https://api.groq.com/openai/v1/chat/completions'
DEFAULT_LLM = {'anthropic': 'claude-haiku-4-5-20251001', 'openai': 'gpt-4o-mini', 'groq': 'llama-3.3-70b-versatile'}
MAX_AUDIO = 24 * 1024 * 1024            # transcription API limit is 25 MB
INTERESTS = [('hot', 'Hot'), ('warm', 'Warm'), ('cold', 'Cold'),
             ('not_interested', 'Not interested'), ('unclear', 'Unclear')]

SYSTEM_PROMPT = """You review phone calls of an admission officer at an education institute in Kerala, India \
(courses such as ACCA, CMA, CA, BBA, MBA and similar). The call is a transcript, often Malayalam mixed with \
English, and may contain transcription mistakes. Judge only what the text shows.
Reply with ONE JSON object and nothing else, with these keys:
"summary": 2-3 plain English sentences about what was discussed and the outcome,
"interest": one of hot, warm, cold, not_interested, unclear (the student's real interest),
"score": integer 1-10, quality of the officer's call (greeting, course and fee explained clearly, answered \
doubts, handled objections, asked for next step, polite),
"issues": short English list of problems (empty string if none),
"next_step": the agreed or recommended next action in one sentence,
"quality_ok": true or false, whether the lead quality set by the officer matches the conversation,
"suggested_quality": one of the allowed quality keys given in the message (the best match for the conversation)."""


def _secs(v):
    from .call_report import _parse_duration_seconds
    return _parse_duration_seconds(v)


class LeadCallLogAI(models.Model):
    _inherit = 'lead.call.log'

    ai_state = fields.Selection([('done', 'Analysed'), ('skipped', 'Skipped'), ('failed', 'Failed')],
                                string='AI Status', copy=False, index=True)
    ai_attempts = fields.Integer(copy=False)
    ai_error = fields.Char(string='AI Error', copy=False)
    ai_on = fields.Datetime(string='Analysed On', copy=False)
    ai_transcript = fields.Text(string='Transcript', copy=False)
    ai_summary = fields.Text(string='AI Summary', copy=False)
    ai_interest = fields.Selection(INTERESTS, string='Student Interest', copy=False)
    ai_score = fields.Integer(string='Officer Score (1-10)', copy=False, aggregator='avg')
    ai_issues = fields.Text(string='Issues', copy=False)
    ai_next_step = fields.Char(string='Next Step', copy=False)
    ai_quality_ok = fields.Boolean(string='Quality matches call', copy=False)
    ai_suggested_quality = fields.Char(string='Suggested Quality', copy=False)
    ai_flag = fields.Boolean(string='Needs review', copy=False, index=True,
                             help='Low officer score, or the lead quality does not match the conversation.')
    ai_lead_name = fields.Char(related='lead_id.name', string='Lead', readonly=True)

    # ------------------------------------------------------------------ #
    @api.model
    def _ai_param(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo().get_param(P + key) or '').strip() or default

    @api.model
    def _ai_enabled(self):
        return self._ai_param('enabled') in ('True', 'true', '1')

    @api.model
    def _ai_keys_ok(self):
        if self._ai_param('llm_provider') == 'groq' and self._ai_param('stt_provider') == 'groq':
            return bool(self._ai_param('stt_key'))          # one Groq key serves both steps
        return bool(self._ai_param('stt_key') and self._ai_param('llm_key'))

    def _ai_audio(self):
        """(bytes, filename, mimetype) of the recording."""
        self.ensure_one()
        if self.recording:
            data = base64.b64decode(self.recording)
            name = self.recording_filename or 'call.webm'
            return data, name, self.recording_mimetype or 'audio/webm'
        url = (self.recording_url or '').strip()
        if not url:
            raise UserError(_('No recording.'))
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        data = b''
        for chunk in r.iter_content(262144):
            data += chunk
            if len(data) > MAX_AUDIO:
                raise UserError(_('Recording is larger than 24 MB.'))
        ext = (url.split('?')[0].rsplit('.', 1)[-1] or 'mp3').lower()[:4]
        if ext not in ('mp3', 'wav', 'm4a', 'ogg', 'webm', 'mp4', 'mpeg', 'flac'):
            ext = 'mp3'
        return data, 'call.' + ext, r.headers.get('Content-Type', 'audio/mpeg').split(';')[0]

    def _ai_transcribe(self):
        data, name, mime = self._ai_audio()
        if len(data) > MAX_AUDIO:
            raise UserError(_('Recording is larger than 24 MB.'))
        groq = self._ai_param('stt_provider', 'openai') == 'groq'
        form = {'model': self._ai_param('stt_model', 'whisper-large-v3' if groq else 'gpt-4o-transcribe')}
        lang = self._ai_param('stt_language')
        if lang:
            form['language'] = lang
        r = None
        for _try in range(3):                     # Cloudflare 502/503/504 or 429 are usually momentary
            r = requests.post(GROQ_STT_URL if groq else STT_URL, headers={'Authorization': 'Bearer ' + self._ai_param('stt_key')},
                              data=form, files={'file': (name, data, mime)}, timeout=240)
            if r.status_code not in (429, 502, 503, 504):
                break
            time.sleep(3 * (_try + 1))
        if r.status_code != 200:
            raise UserError(_('Speech-to-text error %s (the AI service is busy or down, try again in a minute): %s') % (r.status_code, re.sub(r'<[^>]+>', ' ', r.text)[:150]) if r.status_code in (429, 502, 503, 504) else _('Speech-to-text error %s: %s') % (r.status_code, r.text[:200]))
        return (r.json().get('text') or '').strip()

    def _ai_ask(self, user_text):
        provider = self._ai_param('llm_provider', 'anthropic')
        model = self._ai_param('llm_model', DEFAULT_LLM.get(provider, DEFAULT_LLM['anthropic']))
        key = self._ai_param('llm_key')
        if provider == 'groq' and not key and self._ai_param('stt_provider') == 'groq':
            key = self._ai_param('stt_key')
        if provider in ('openai', 'groq'):
            r = requests.post(GROQ_CHAT_URL if provider == 'groq' else OPENAI_CHAT_URL, headers={'Authorization': 'Bearer ' + key}, timeout=120, json={
                'model': model, 'response_format': {'type': 'json_object'}, 'temperature': 0.2,
                'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                             {'role': 'user', 'content': user_text}]})
            if r.status_code != 200:
                raise UserError(_('AI error %s: %s') % (r.status_code, r.text[:200]))
            return r.json()['choices'][0]['message']['content']
        r = requests.post(ANTHROPIC_URL, timeout=120, headers={
            'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}, json={
            'model': model, 'max_tokens': 800, 'system': SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': user_text}]})
        if r.status_code != 200:
            raise UserError(_('AI error %s: %s') % (r.status_code, r.text[:200]))
        return ''.join(b.get('text', '') for b in r.json().get('content', []))

    def _ai_prompt(self, transcript):
        lead = self.lead_id
        qkeys = [k for k, _l in lead._fields['lead_quality']._description_selection(self.env)]
        qlabel = dict(lead._fields['lead_quality']._description_selection(self.env)).get(lead.lead_quality, '-')
        return (
            "Call type: %s. Duration: %s. Officer: %s.\nLead quality set by the officer now: %s (%s).\n"
            "Allowed quality keys: %s.\nOfficer remarks: %s\n\nTRANSCRIPT:\n%s"
        ) % (self.call_type or '-', self.duration or '-', self.user_id.name or '-', lead.lead_quality or '-',
             qlabel, ', '.join(qkeys), (self.remarks or '-')[:300], transcript[:12000])

    @staticmethod
    def _ai_json(text):
        m = re.search(r'\{.*\}', text or '', re.S)
        if not m:
            raise UserError(_('AI did not return JSON.'))
        return json.loads(m.group(0))

    def _ai_analyse_one(self):
        """Analyse this call. Raises on failure (caller records it)."""
        self.ensure_one()
        transcript = self._ai_transcribe()
        if len(transcript) < 25:
            self.write({'ai_state': 'skipped', 'ai_transcript': transcript, 'ai_on': fields.Datetime.now(),
                        'ai_error': 'No speech found'})
            return
        res = self._ai_json(self._ai_ask(self._ai_prompt(transcript)))
        interest = res.get('interest') if res.get('interest') in dict(INTERESTS) else 'unclear'
        try:
            score = max(1, min(10, int(res.get('score') or 0)))
        except (TypeError, ValueError):
            score = 0
        issues = res.get('issues')
        if isinstance(issues, list):
            issues = '; '.join(str(i) for i in issues)
        ok = bool(res.get('quality_ok', True))
        self.write({
            'ai_state': 'done', 'ai_error': False, 'ai_on': fields.Datetime.now(), 'ai_transcript': transcript,
            'ai_summary': str(res.get('summary') or '')[:2000], 'ai_interest': interest, 'ai_score': score,
            'ai_issues': str(issues or '')[:1500], 'ai_next_step': str(res.get('next_step') or '')[:250],
            'ai_quality_ok': ok, 'ai_suggested_quality': str(res.get('suggested_quality') or '')[:40],
            'ai_flag': (0 < score <= 4) or not ok,
        })

    # ------------------------------------------------------------------ #
    def action_ai_analyse(self):
        """Button: analyse now (needs the API keys; works even when the automatic switch is off)."""
        if not self._ai_keys_ok():
            raise UserError(_('Set the speech-to-text key and the AI key in Settings > Lead Management first.'))
        for rec in self.sudo():
            if not rec.has_recording:
                raise UserError(_('This call has no recording.'))
            try:
                rec._ai_analyse_one()
            except UserError:
                raise
            except Exception as e:  # noqa: BLE001
                raise UserError(_('AI analysis failed: %s') % str(e)[:200])
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('AI call analysis'), 'message': _('Done.'), 'type': 'success', 'sticky': False}}

    @api.model
    def cron_ai_analyse_calls(self):
        if not self._ai_enabled() or not self._ai_keys_ok():
            return
        min_s = int(self._ai_param('min_seconds', '30') or 30)
        limit = int(self._ai_param('daily_limit', '100') or 100)
        age = int(self._ai_param('max_age_days', '2') or 2)
        today = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        used = self.sudo().search_count([('ai_on', '>=', today), ('ai_state', 'in', ['done', 'skipped'])])
        room = limit - used
        if room <= 0:
            return
        since = fields.Datetime.subtract(fields.Datetime.now(), days=age)
        cands = self.sudo().search([
            ('ai_state', '=', False), ('ai_attempts', '<', 3), ('has_recording', '=', True),
            ('lead_id', '!=', False), ('call_time', '>=', since)], order='call_time desc', limit=60)
        done = 0
        for rec in cands:
            if done >= min(room, 6):                  # a few per run: the cron stays short
                break
            if _secs(rec.duration) < min_s:
                continue
            try:
                with self.env.cr.savepoint():
                    rec._ai_analyse_one()
            except Exception as e:  # noqa: BLE001
                _logger.warning('AI call analysis failed for call %s: %s', rec.id, e)
                att = rec.ai_attempts + 1
                rec.write({'ai_attempts': att, 'ai_error': str(e)[:200],
                           'ai_state': 'failed' if att >= 3 else False})
            done += 1
            self.env.cr.commit()
