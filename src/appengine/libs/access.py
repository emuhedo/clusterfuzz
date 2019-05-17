# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""access.py contains static methods around access permissions."""

from builtins import object
from builtins import range

from base import errors
from base import external_users
from base import utils
from config import db_config
from config import local_config
from datastore import data_handler
from issue_management import issue_tracker_utils
from libs import auth
from libs import helpers


def _is_privileged_user(email):
  """Check if an email is in the privileged users list."""
  privileged_user_emails = (db_config.get_value('privileged_users') or
                            '').splitlines()
  for privileged_user_email in privileged_user_emails:
    if utils.emails_equal(email, privileged_user_email):
      return True

  return False


def get_user_job_type():
  """Return the job_type that is assigned to the current user. None means one
    can access any job type. You might want to invoke get_access(..) with
    the job type afterward."""
  email = helpers.get_user_email()
  privileged_user_emails = (db_config.get_value('privileged_users') or
                            '').splitlines()
  for privileged_user_email in privileged_user_emails:
    if ';' in privileged_user_email:
      tokens = privileged_user_email.split(';')
      privileged_user_real_email = tokens[0]
      privileged_user_job_type = tokens[1]
      if utils.emails_equal(email, privileged_user_real_email):
        return privileged_user_job_type
  return None


def _is_domain_allowed(email):
  """Check if the email's domain is allowed."""
  domains = local_config.AuthConfig().get('whitelisted_domains', default=[])
  for domain in domains:
    if utils.normalize_email(email).endswith('@%s' % domain.lower()):
      return True

  return False


class UserAccess(object):
  Allowed, Denied, Redirected = list(range(3))  # pylint: disable=invalid-name


def has_access(need_privileged_access=False, job_type=None, fuzzer_name=None):
  """Check if the user has access."""
  result = get_access(
      need_privileged_access=need_privileged_access,
      job_type=job_type,
      fuzzer_name=fuzzer_name)

  return result == UserAccess.Allowed


def get_access(need_privileged_access=False, job_type=None, fuzzer_name=None):
  """Return 'allowed', 'redirected', or 'failed'."""
  if auth.is_current_user_admin():
    return UserAccess.Allowed

  user = auth.get_current_user()
  if not user:
    return UserAccess.Redirected

  email = user.email
  if _is_privileged_user(email):
    return UserAccess.Allowed

  if job_type and external_users.is_job_allowed_for_user(email, job_type):
    return UserAccess.Allowed

  if (fuzzer_name and
      external_users.is_fuzzer_allowed_for_user(email, fuzzer_name)):
    return UserAccess.Allowed

  if not need_privileged_access and _is_domain_allowed(email):
    return UserAccess.Allowed

  return UserAccess.Denied


def can_user_access_testcase(testcase):
  """Checks if the current user can access the testcase."""
  if has_access(
      fuzzer_name=testcase.fuzzer_name,
      job_type=testcase.job_type,
      need_privileged_access=testcase.security_flag):
    return True

  user_email = helpers.get_user_email()
  if testcase.uploader_email and testcase.uploader_email == user_email:
    return True

  # Allow owners of bugs to see associated test cases and test case groups.
  issue_id = testcase.bug_information or testcase.group_bug_information
  if not issue_id:
    return False

  issue_id = int(issue_id)
  itm = issue_tracker_utils.get_issue_tracker_manager(testcase)
  issue = itm.get_issue(issue_id)
  if not issue:
    return False

  # Look at both associated issue and original issue (in case of dupes).
  issues_to_check = [issue]
  if issue.merged_into:
    original_issue = itm.get_original_issue(issue_id)
    if original_issue:
      issues_to_check.append(original_issue)

  config = db_config.get()
  for issue in issues_to_check:
    if config.relax_testcase_restrictions or _is_domain_allowed(user_email):
      if (any(utils.emails_equal(user_email, cc) for cc in issue.cc) or
          utils.emails_equal(user_email, issue.owner) or
          utils.emails_equal(user_email, issue.reporter)):
        return True

    if utils.emails_equal(user_email, issue.owner):
      return True

  return False


def check_access_and_get_testcase(testcase_id):
  """Check the failed attempt count and get the testcase."""
  if not helpers.get_user_email():
    raise helpers.UnauthorizedException()

  if not testcase_id:
    raise helpers.EarlyExitException('No test case specified!', 404)

  try:
    testcase = data_handler.get_testcase_by_id(testcase_id)
  except errors.InvalidTestcaseError:
    raise helpers.EarlyExitException('Invalid test case!', 404)

  if not can_user_access_testcase(testcase):
    raise helpers.AccessDeniedException()

  return testcase
