-- Additive upgrade of the locally applied initial answer_runs schema.
-- Existing feedback and run rows are retained; historic execution is not synthesized.
ALTER TABLE public.answer_runs ADD COLUMN id uuid DEFAULT gen_random_uuid();
UPDATE public.answer_runs SET id=gen_random_uuid() WHERE id IS NULL;
ALTER TABLE public.answer_runs ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.answer_feedback DROP CONSTRAINT IF EXISTS answer_feedback_run_id_fkey;
ALTER TABLE public.answer_feedback DROP CONSTRAINT IF EXISTS answer_feedback_run_id_fkey1;
ALTER TABLE public.answer_runs DROP CONSTRAINT answer_runs_pkey;
ALTER TABLE public.answer_runs ADD CONSTRAINT answer_runs_pkey PRIMARY KEY (id);
ALTER TABLE public.answer_runs ALTER COLUMN answer_id DROP NOT NULL;
ALTER TABLE public.answer_runs ADD CONSTRAINT answer_runs_answer_id_key UNIQUE (answer_id);
ALTER TABLE public.answer_runs ALTER COLUMN execution DROP NOT NULL;
ALTER TABLE public.answer_runs ALTER COLUMN answer_status DROP NOT NULL;

ALTER TABLE public.answer_runs
  ADD COLUMN request_id uuid,
  ADD COLUMN environment text NOT NULL DEFAULT 'unknown' CHECK (environment IN ('local','production','staging','unknown')),
  ADD COLUMN agent_mode text NOT NULL DEFAULT 'unknown',
  ADD COLUMN started_at timestamptz,
  ADD COLUMN finished_at timestamptz,
  ADD COLUMN status text NOT NULL DEFAULT 'incomplete' CHECK (status IN ('running','completed','failed','incomplete')),
  ADD COLUMN versions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(versions)='object'),
  ADD COLUMN capture_status text NOT NULL DEFAULT 'partial' CHECK (capture_status IN ('complete','partial')),
  ADD COLUMN expires_at timestamptz NOT NULL DEFAULT (now() + interval '90 days');

-- Preserve existing feedback links while run identifiers become independent of answer identifiers.
UPDATE public.answer_feedback f SET run_id=r.id
FROM public.answer_runs r WHERE f.run_id=r.answer_id;

-- Legacy summary rows have no trustworthy start/finish times or step sequence. Keep them partial.
UPDATE public.answer_runs SET started_at=NULL,finished_at=NULL,status='incomplete',capture_status='partial',
  versions='{}'::jsonb,expires_at=created_at + interval '90 days';

-- Replace the initial migration's answer_id FK with the independent execution id.
ALTER TABLE public.answer_feedback
  ADD CONSTRAINT answer_feedback_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.answer_runs(id) ON DELETE SET NULL,
  ADD COLUMN reviewed_by text,
  ADD COLUMN eval_question text,
  ADD COLUMN expected_result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(expected_result)='object'),
  ADD COLUMN eval_approved_by text,
  ADD COLUMN eval_approved_at timestamptz;

CREATE TABLE public.answer_run_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES public.answer_runs(id) ON DELETE CASCADE,
  parent_step_id uuid,
  step_kind text NOT NULL CHECK (step_kind IN ('node','tool','model','answer')),
  name text NOT NULL CHECK (char_length(name) <= 100),
  sequence bigint NOT NULL CHECK (sequence > 0),
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  duration_ms numeric(12,2) CHECK (duration_ms >= 0),
  status text NOT NULL CHECK (status IN ('completed','rejected','failed','incomplete')),
  input_summary jsonb CHECK (input_summary IS NULL OR jsonb_typeof(input_summary) IN ('object','array')),
  output_summary jsonb CHECK (output_summary IS NULL OR jsonb_typeof(output_summary) IN ('object','array')),
  error_code text,
  error_type text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata)='object'),
  UNIQUE (run_id, sequence),
  UNIQUE (id, run_id),
  CONSTRAINT answer_run_steps_parent_same_run_fk
    FOREIGN KEY (parent_step_id, run_id) REFERENCES public.answer_run_steps(id, run_id) ON DELETE CASCADE
);

CREATE INDEX answer_runs_request_idx ON public.answer_runs(thread_id, request_id, started_at DESC);
CREATE INDEX answer_runs_answer_idx ON public.answer_runs(answer_id);
CREATE INDEX answer_runs_conversation_started_idx ON public.answer_runs(conversation_id, started_at DESC);
CREATE INDEX answer_runs_expiry_idx ON public.answer_runs(expires_at);
CREATE INDEX answer_run_steps_run_idx ON public.answer_run_steps(run_id, sequence);
CREATE INDEX answer_run_steps_lookup_idx ON public.answer_run_steps(name, status, started_at DESC);
CREATE INDEX IF NOT EXISTS answer_feedback_run_idx ON public.answer_feedback(run_id);

ALTER TABLE public.answer_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.answer_run_steps ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.answer_runs, public.answer_run_steps FROM public, anon, authenticated;
GRANT ALL ON public.answer_runs, public.answer_run_steps TO service_role;
COMMENT ON TABLE public.answer_run_steps IS 'Bounded server-side node/tool/model summaries; no model prompt/response body or user transcript.';
COMMENT ON COLUMN public.answer_runs.id IS 'Independent execution id. answer_id is null until a response exists.';
