from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Classroom, AttendanceSession, Attendance, Exam, Mark, AuditEvent
from . import permissions as access

class Conflict(ValidationError):
    pass

def audit(actor, branch, action, target, details=None):
    AuditEvent.objects.create(actor=actor, branch=branch, action=action, target=str(target)[:180], details=details or {})

@transaction.atomic
def save_register(actor, classroom, day, statuses, expected_version, reason=''):
    # The classroom lock also serializes first creation when no register exists yet.
    classroom = Classroom.objects.select_for_update().get(pk=classroom.pk)
    if not access.can_attend(actor, classroom):
        raise PermissionDenied
    if day > timezone.localdate() or not classroom.year.starts_on <= day <= classroom.year.ends_on:
        raise ValidationError('Attendance date is outside the permitted range.')
    eligible = set(access.roster(classroom, day).values_list('pk', flat=True))
    if not eligible or set(statuses) != eligible or any(v not in Attendance.Status.values for v in statuses.values()):
        raise ValidationError('Mark every enrolled student using a valid attendance status.')
    session = AttendanceSession.objects.select_for_update().filter(classroom=classroom, date=day).first()
    if (session.version if session else 0) != expected_version:
        raise Conflict('Another user changed this register. Reload before saving.')
    old = {}
    if session:
        if not reason.strip():
            raise ValidationError('Enter a reason for correcting this register.')
        old = {str(k): v for k,v in session.records.values_list('enrollment_id','status')}
        session.version += 1
        session.recorded_by = actor
        session.save()
    else:
        session = AttendanceSession.objects.create(classroom=classroom, date=day, recorded_by=actor)
    for enrollment_id, status in statuses.items():
        Attendance.objects.update_or_create(session=session, enrollment_id=enrollment_id, defaults={'status': status})
    audit(actor, classroom.branch, 'attendance.saved', f'{classroom} · {day}', {'before':old,'after':{str(k):v for k,v in statuses.items()},'reason':reason})
    return session

@transaction.atomic
def save_marks(actor, exam, entries, expected_version):
    Classroom.objects.select_for_update().get(pk=exam.classroom_id)
    exam = Exam.objects.select_for_update().get(pk=exam.pk)
    if not access.can_mark(actor, exam):
        raise PermissionDenied
    if exam.version != expected_version:
        raise Conflict('This mark sheet changed. Reload before saving.')
    if exam.status != 'draft':
        raise ValidationError('Marks are locked after submission. Ask the principal to reopen this exam.')
    eligible = set(access.roster(exam.classroom, exam.date).values_list('pk',flat=True))
    if set(entries) != eligible:
        raise ValidationError('The student roster changed. Reload this page.')
    before = {str(m.enrollment_id): {'score':str(m.score) if m.score is not None else None,'absent':m.absent} for m in exam.marks.all()}
    for enrollment_id, entry in entries.items():
        score, absent = entry
        if score is None and not absent:
            Mark.objects.filter(exam=exam, enrollment_id=enrollment_id).delete()
        else:
            Mark.objects.update_or_create(exam=exam, enrollment_id=enrollment_id, defaults={'score':score,'absent':absent})
    exam.version += 1
    exam.save()
    audit(actor, exam.classroom.branch, 'marks.saved', exam, {'before':before,'after':{str(k):{'score':str(v[0]) if v[0] is not None else None,'absent':v[1]} for k,v in entries.items()}})

@transaction.atomic
def transition_exam(actor, exam, action, expected_version, reason=''):
    Classroom.objects.select_for_update().get(pk=exam.classroom_id)
    exam = Exam.objects.select_for_update().get(pk=exam.pk)
    if exam.version != expected_version:
        raise Conflict('This exam changed. Reload before continuing.')
    if action == 'submit':
        if not access.can_mark(actor, exam):
            raise PermissionDenied
        if exam.status != 'draft':
            raise ValidationError('Only draft exams can be submitted.')
        target = 'submitted'
    elif action == 'publish':
        if not access.can_publish(actor, exam):
            raise PermissionDenied
        if exam.status != 'submitted':
            raise ValidationError('Submit the exam for review before publishing.')
        target = 'published'
    elif action == 'reopen':
        if not access.can_publish(actor, exam):
            raise PermissionDenied
        if exam.status == 'draft' or not reason.strip():
            raise ValidationError('Reopening requires a locked exam and a correction reason.')
        target = 'draft'
    else:
        raise ValidationError('Unknown exam action.')
    if action in ('submit','publish'):
        if exam.date > timezone.localdate():
            raise ValidationError('An upcoming exam cannot be submitted or published.')
        eligible = set(access.roster(exam.classroom, exam.date).values_list('pk',flat=True))
        if not eligible or set(exam.marks.values_list('enrollment_id',flat=True)) != eligible:
            raise ValidationError('Enter a score or absence for every enrolled student before continuing.')
    old = exam.status
    exam.status = target
    exam.version += 1
    exam.published_by = actor if action == 'publish' else None
    exam.published_at = timezone.now() if action == 'publish' else None
    exam.save()
    audit(actor, exam.classroom.branch, f'exam.{action}', exam, {'from':old,'to':target,'reason':reason})
    return exam

def attendance_summary(rows):
    counts = {v:0 for v in Attendance.Status.values}
    for status in rows.values_list('status',flat=True):
        counts[status] += 1
    denominator = counts['P'] + counts['L'] + counts['A']
    return {**counts, 'total':sum(counts.values()), 'rate':round(100*(counts['P']+counts['L'])/denominator,1) if denominator else None}

def mark_summary(marks):
    marks = list(marks)
    possible = sum((m.exam.max_marks for m in marks), Decimal(0))
    earned = sum((m.score or Decimal(0) for m in marks), Decimal(0))
    return {'count':len(marks), 'earned':earned, 'possible':possible, 'percentage':round(earned/possible*100,1) if possible else None, 'passed':sum(m.passed for m in marks)}
