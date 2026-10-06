import { sanitizeAnalyticsEvent, setAnalyticsAllowed } from './analytics';

beforeEach(() => { localStorage.clear(); window.history.replaceState({}, '', '/chat?q=비밀질문'); });
test('only allowed events and metadata reach analytics, stripping text, identity and URL secrets', () => {
  const result = sanitizeAnalyticsEvent({ event: 'question_submitted', properties: {
    token: 'project-token', distinct_id: 'anonymous-id', member: true, question: '기밀', answer: '기밀답변',
    email: 'private@example.com', conversation_id: 'private-chat', '$current_url': 'https://site/chat?q=secret',
    '$referrer': 'https://google/?q=private', '$initial_referrer': 'https://site/?code=secret', '$set': { email: 'secret' }, '$title': '대화제목',
  } });
  expect(result.properties).toEqual({ token: 'project-token', distinct_id: 'anonymous-id', member: true,
    $current_url: window.location.origin + '/chat', $pathname: '/chat', $ip: null, $geoip_disable: true, $process_person_profile: false });
  expect(sanitizeAnalyticsEvent({ event: '$autocapture', properties: { text: 'secret' } })).toBeNull();
  expect(sanitizeAnalyticsEvent({ event: '$snapshot', properties: { data: 'secret' } })).toBeNull();
});
test('opt out drops events and opt in restores collection without identifying the account', () => {
  setAnalyticsAllowed(false);
  expect(sanitizeAnalyticsEvent({ event: '$pageview', properties: {} })).toBeNull();
  setAnalyticsAllowed(true);
  expect(sanitizeAnalyticsEvent({ event: '$pageview', properties: { page: '/' } }).properties.$current_url).toBe(window.location.origin + '/');
});
