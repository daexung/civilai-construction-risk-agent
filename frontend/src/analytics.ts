import type { PostHog } from 'posthog-js';

const OPT_OUT_KEY = 'poomsemi-analytics-opt-out';
const EVENTS = new Set(['$pageview', 'question_submitted', 'estimate_downloaded', 'feedback_submitted', 'answer_rated']);
const SAFE_PROPERTIES = new Set(['token', 'distinct_id', '$device_id', '$session_id', '$window_id', '$lib', '$lib_version',
  '$browser', '$browser_version', '$os', '$os_version', '$device_type', '$screen_height', '$screen_width',
  '$viewport_height', '$viewport_width', '$host', '$pathname', '$process_person_profile', '$is_identified',
  'member', 'category', 'rating', 'reason', 'page']);
let client: Promise<PostHog | null> | null = null;
let lastPage = '';

export function analyticsAllowed(): boolean {
  try { return localStorage.getItem(OPT_OUT_KEY) !== 'true' && navigator.doNotTrack !== '1'; }
  catch { return false; }
}

export function setAnalyticsAllowed(allowed: boolean): void {
  try { localStorage.setItem(OPT_OUT_KEY, String(!allowed)); } catch { return; }
  if (!allowed) void client?.then(value => value?.opt_out_capturing());
  else { lastPage = ''; void client?.then(value => { if (value) value.opt_in_capturing({ captureEventName: false }); else client = null; }); }
}

function safePage(path: string): string {
  return ['/', '/chat', '/terms', '/privacy'].includes(path) ? path : '/other';
}

// A strict allowlist also removes SDK-generated referrers, page titles and query strings.
export function sanitizeAnalyticsEvent<T extends { event: string; properties: Record<string, any> }>(event: T | null): T | null {
  if (!event || !EVENTS.has(event.event) || !analyticsAllowed()) return null;
  const properties: Record<string, any> = {};
  for (const [key, value] of Object.entries(event.properties)) {
    if (SAFE_PROPERTIES.has(key) && ['string', 'number', 'boolean'].includes(typeof value)) properties[key] = value;
  }
  const page = safePage(event.event === '$pageview' && typeof properties.page === 'string' ? properties.page : window.location.pathname);
  properties.$current_url = window.location.origin + page;
  properties.$pathname = page;
  properties.$ip = null;
  properties.$geoip_disable = true;
  properties.$process_person_profile = false;
  return { ...event, properties };
}

function getClient(): Promise<PostHog | null> {
  const key = process.env.REACT_APP_POSTHOG_KEY;
  const host = process.env.REACT_APP_POSTHOG_HOST;
  if (!key || !['https://us.i.posthog.com', 'https://eu.i.posthog.com'].includes(host ?? '') || !analyticsAllowed()) return Promise.resolve(null);
  // Local development is excluded unless explicitly enabled for installation testing.
  if (['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
    && process.env.REACT_APP_POSTHOG_TRACK_LOCAL !== 'true') return Promise.resolve(null);
  if (!client) client = import('posthog-js').then(({ default: posthog }) => {
    if (!analyticsAllowed()) return null;
    posthog.init(key, { api_host: host, autocapture: false, capture_pageview: false, capture_pageleave: false,
      disable_session_recording: true, disable_surveys: true, capture_performance: false,
      capture_heatmaps: false, advanced_disable_feature_flags: true, disable_external_dependency_loading: true,
      person_profiles: 'never', persistence: 'localStorage', respect_dnt: true, ip: false,
      before_send: sanitizeAnalyticsEvent });
    return posthog;
  }).catch(() => null);
  return client;
}

export function trackEvent(event: 'question_submitted' | 'estimate_downloaded' | 'feedback_submitted' | 'answer_rated',
  properties: { member?: boolean; category?: string; rating?: string; reason?: string } = {}): void {
  void getClient().then(value => { if (analyticsAllowed()) value?.capture(event, properties); }).catch(() => {});
}

export function trackPage(path: string): void {
  if (!['/', '/chat', '/terms', '/privacy'].includes(path) || lastPage === path) return;
  lastPage = path;
  void getClient().then(value => { if (analyticsAllowed()) value?.capture('$pageview', { page: path }); }).catch(() => {});
}
