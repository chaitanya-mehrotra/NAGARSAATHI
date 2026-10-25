-- NAGARSAATHI Phase 2. Run once in the Supabase SQL editor.
create extension if not exists pgcrypto;
create table public.complaints (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id),
 submission_key uuid not null unique,
 reference text not null unique default ('NS-' || upper(substr(replace(gen_random_uuid()::text,'-',''),1,12))),
 issue_type text not null check (issue_type in ('pothole','waterlogging','both')),
 description text not null check (char_length(btrim(description)) between 10 and 500),
 latitude double precision not null check (latitude between -90 and 90),
 longitude double precision not null check (longitude between -180 and 180),
 landmark text check (char_length(landmark)<=150),
 photo_path text not null unique,
 status text not null default 'submitted' check (status in ('submitted','under_review','resolved')),
 analysis_state text not null default 'not_requested' check (analysis_state in ('not_requested','completed','failed')),
 verification_status text check (verification_status in ('Supported by image','Partially supported','Possible mismatch','Could not verify')),
 detections jsonb not null default '[]'::jsonb check(jsonb_typeof(detections)='array'),
 model_version text, image_width integer check(image_width>0), image_height integer check(image_height>0),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index complaints_created_idx on public.complaints(created_at desc);
create index complaints_owner_created_idx on public.complaints(owner_id,created_at desc);
create index complaints_status_issue_idx on public.complaints(status,issue_type);
alter table public.complaints enable row level security;
-- Browser receives no direct table grants. FastAPI validates the bearer JWT with
-- Auth and writes only validated fields, with an owner derived from that JWT.
revoke all on public.complaints from anon,authenticated;
-- Defense in depth if a maintainer later grants access:
create policy own_insert on public.complaints for insert to authenticated
with check(owner_id=(select auth.uid()) and status='submitted' and analysis_state='not_requested'
and verification_status is null and detections='[]'::jsonb and model_version is null
and image_width is null and image_height is null);
create policy own_read on public.complaints for select to authenticated using(owner_id=(select auth.uid()));
-- No UPDATE or DELETE policy. No browser writes to trusted inference fields.
create table public.complaint_events (
 id uuid primary key references public.complaints(id) on delete cascade,
 updated_at timestamptz not null default now()
);
alter table public.complaint_events enable row level security;
revoke all on public.complaint_events from anon,authenticated;
grant select on public.complaint_events to authenticated;
create policy shared_change_signal on public.complaint_events for select to authenticated using(true);
create function public.stamp_complaint() returns trigger language plpgsql set search_path=public as $$
begin new.updated_at=now(); return new; end $$;
create trigger complaint_stamp before update on public.complaints for each row execute function public.stamp_complaint();
create function public.signal_complaint() returns trigger language plpgsql security definer set search_path=public as $$
begin insert into public.complaint_events(id,updated_at) values(new.id,now())
on conflict(id) do update set updated_at=excluded.updated_at; return new; end $$;
revoke execute on function public.signal_complaint() from public,anon,authenticated;
create trigger complaint_signal after insert or update on public.complaints for each row execute function public.signal_complaint();
alter publication supabase_realtime add table public.complaint_events;
create function public.complaint_metrics() returns jsonb language sql security definer set search_path=public as $$
select jsonb_build_object('total',count(*),'pothole',count(*) filter(where issue_type in ('pothole','both')),
'waterlogging',count(*) filter(where issue_type in ('waterlogging','both')),
'resolved',count(*) filter(where status='resolved'),'submitted',count(*) filter(where status='submitted'),
'under_review',count(*) filter(where status='under_review')) from public.complaints $$;
revoke execute on function public.complaint_metrics() from public,anon,authenticated;
grant execute on function public.complaint_metrics() to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('complaint-photos','complaint-photos',false,10485760,array['image/jpeg'])
on conflict(id) do nothing;
-- No client bucket policies. Only the authenticated API signs individual photos.

grant all on public.complaints,public.complaint_events to service_role;
