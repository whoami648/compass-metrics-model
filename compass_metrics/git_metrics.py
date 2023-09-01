""" Set of git related metrics """

from compass_metrics.db_dsl import (get_updated_since_query,
                                    get_uuid_count_query,
                                    get_message_list_query,
                                    get_repo_message_query)
from compass_metrics.contributor_metrics import get_contributor_list
from compass_common.datetime import (get_time_diff_months,
                                     check_times_has_overlap,
                                     get_oldest_date,
                                     get_latest_date,
                                     get_date_list)
from datetime import timedelta
import numpy as np
import math


def created_since(client, git_index, date, repo_list):
    """ Determine how long a repository has existed since it was created (in months). """
    created_since_list = []
    for repo in repo_list:
        query_first_commit_since = get_updated_since_query(
            [repo], date_field='grimoire_creation_date', to_date=date, order="asc")
        first_commit_since = client.search(index=git_index, body=query_first_commit_since)['hits']['hits']
        if len(first_commit_since) > 0:
            creation_since = first_commit_since[0]['_source']["grimoire_creation_date"]
            created_since_list.append(
                get_time_diff_months(creation_since, str(date)))

    result = {
        "created_since": round(sum(created_since_list), 4) if created_since_list else None
    }
    return result


def updated_since(client, git_index, repo_index, date, repo_list, level):
    """ Determine the average time per repository since the repository was last updated (in months). """
    updated_since_list = []
    for repo in repo_list:
        if level in ["project", "community"]:
            repo_message_query = get_repo_message_query(repo)
            repo_message_list = client.search(index=repo_index, body=repo_message_query)['hits']['hits']
            if len(repo_message_list) > 0:
                repo_message = repo_message_list[0]['_source']
                archived_at = repo_message.get('archivedAt')
                if archived_at is not None and archived_at < date.strftime("%Y-%m-%d"):
                    continue

        query_updated_since = get_updated_since_query(
            [repo], date_field='metadata__updated_on', to_date=date)
        updated_since = client.search(index=git_index, body=query_updated_since)['hits']['hits']
        if updated_since:
            updated_since_list.append(get_time_diff_months(
                updated_since[0]['_source']["metadata__updated_on"], str(date)))
    result = {
        "updated_since": float(round(sum(updated_since_list) / len(updated_since_list), 4)) if len(updated_since_list) > 0 else None
    }
    return result


def commit_frequency(client, contributors_index, date, repo_list):
    """ Determine the average number of commits per week in the past 90 days. """
    from_date = date - timedelta(days=90)
    to_date = date
    commit_contributor_list = get_contributor_list(client, contributors_index, from_date, to_date, repo_list,
                                                   "code_commit_date_list")
    result = {
        'commit_frequency': get_commit_count(from_date, to_date, commit_contributor_list)/12.85,
        'commit_frequency_bot': get_commit_count(from_date, to_date, commit_contributor_list, is_bot=True)/12.85,
        'commit_frequency_without_bot': get_commit_count(from_date, to_date, commit_contributor_list, is_bot=False)/12.85
    }
    return result


def org_count(client, contributors_index, date, repo_list):
    """ Number of organizations to which active code contributors belong in the past 90 days """
    from_date = date - timedelta(days=90)
    to_date = date
    commit_contributor_list = get_contributor_list(client, contributors_index, from_date, to_date, repo_list,
                                                   "code_commit_date_list")
    org_name_set = set()
    for contributor in commit_contributor_list:
        for org in contributor["org_change_date_list"]:
            if org.get("org_name") is not None and check_times_has_overlap(
                    org["first_date"], org["last_date"], from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")):
                org_name_set.add(org.get("org_name"))
    result = {
        'org_count': len(org_name_set)
    }
    return result


def org_commit_frequency(client, contributors_index, date, repo_list):
    """ Determine the average number of commits with organization affiliation per week in the past 90 days. """
    from_date = date - timedelta(days=90)
    to_date = date
    commit_contributor_list = get_contributor_list(client, contributors_index, from_date, to_date, repo_list,
                                                   "code_commit_date_list")
    from_date_str = from_date.strftime("%Y-%m-%d")
    to_date_str = to_date.strftime("%Y-%m-%d")
    total_commit_count = 0
    org_commit_count = 0
    org_commit_bot_count = 0
    org_commit_without_bot_count = 0
    org_commit_detail_dict = {}

    for contributor in commit_contributor_list:
        commit_date_list = [x for x in sorted(contributor["code_commit_date_list"]) if from_date_str <= x < to_date_str]
        total_commit_count += len(commit_date_list)
        for commit_date in commit_date_list:
            for org in contributor["org_change_date_list"]:
                if org["org_name"] is not None and org["first_date"] <= commit_date < org["last_date"]:
                    org_commit_count += 1
                    if contributor["is_bot"]:
                        org_commit_bot_count += 1
                    else:
                        org_commit_without_bot_count += 1
                    break

            org_name_set = set()
            for org in contributor["org_change_date_list"]:
                org_name = org.get("org_name") if org.get("org_name") else org.get("domain")
                if org_name in org_name_set:
                    continue
                org_name_set.add(org_name)
                is_org = True if org.get("org_name") else False
                count = org_commit_detail_dict.get(org_name, {}).get("org_commit", 0)
                if org["first_date"] <= commit_date < org["last_date"]:
                    count += 1
                org_commit_detail_dict[org_name] = {
                    "org_name": org_name,
                    "is_org": is_org,
                    "org_commit": count
                }

    org_commit_frequency_list = []
    for x in org_commit_detail_dict.values():
        if x["org_commit"] == 0:
            continue
        if x["is_org"]:
            org_commit_percentage_by_org = 0 if org_commit_count == 0 else x["org_commit"] / org_commit_count
        else:
            org_commit_percentage_by_org = 0 if (total_commit_count - org_commit_count) == 0 else \
                x["org_commit"] / (total_commit_count - org_commit_count)
        x["org_commit_percentage_by_org"] = round(org_commit_percentage_by_org, 4)
        x["org_commit_percentage_by_total"] = 0 if total_commit_count == 0 else round(x["org_commit"] / total_commit_count, 4)
        org_commit_frequency_list.append(x)
    org_commit_frequency_list = sorted(org_commit_frequency_list, key=lambda x: x["org_commit"], reverse=True)
    result = {
        'org_commit_frequency': round(org_commit_count/12.85, 4),
        'org_commit_frequency_bot': round(org_commit_bot_count/12.85, 4),
        'org_commit_frequency_without_bot': round(org_commit_without_bot_count/12.85, 4),
        'org_commit_frequency_list': org_commit_frequency_list
    }
    return result


def org_contribution_last(client, contributors_index, date, repo_list):
    """ Total contribution time of all organizations to the community in the past 90 days (weeks). """
    from_date = date - timedelta(days=90)
    to_date = date
    commit_contributor_list = get_contributor_list(client, contributors_index, from_date, to_date, repo_list,
                                                   "code_commit_date_list")
    contribution_last = 0
    repo_contributor_group_dict = {}
    for contributor in commit_contributor_list:
        repo_contributor_list = repo_contributor_group_dict.get(contributor["repo_name"], [])
        repo_contributor_list.append(contributor)
        repo_contributor_group_dict[contributor["repo_name"]] = repo_contributor_list

    date_list = get_date_list(begin_date=str(from_date), end_date=str(to_date), freq='7D')
    for repo, repo_contributor_list in repo_contributor_group_dict.items():
        for day in date_list:
            org_name_set = set()
            from_day = (day - timedelta(days=7)).strftime("%Y-%m-%d")
            to_day = day.strftime("%Y-%m-%d")
            for contributor in repo_contributor_list:
                for org in contributor["org_change_date_list"]:
                    if org.get("org_name") is not None and check_times_has_overlap(org["first_date"], org["last_date"],
                                                                                   from_day, to_day):
                        for commit_date in contributor["code_commit_date_list"]:
                            if from_day <= commit_date <= to_day:
                                org_name_set.add(org.get("org_name"))
                                break
            contribution_last += len(org_name_set)
    result = {
        "org_contribution_last": contribution_last
    }
    return result


def is_maintained(client, git_index, date, repos_list, level):
    is_maintained_list = []
    git_repos_list = [repo_url+'.git' for repo_url in repos_list]
    if level == "repo":
        date_list_maintained = get_date_list(begin_date=str(
            date-timedelta(days=90)), end_date=str(date), freq='7D')
        for day in date_list_maintained:
            query_git_commit_i = get_uuid_count_query(
                "cardinality", git_repos_list, "hash", size=0, from_date=day-timedelta(days=7), to_date=day)
            commit_frequency_i = client.search(index=git_index, body=query_git_commit_i)[
                'aggregations']["count_of_uuid"]['value']
            if commit_frequency_i > 0:
                is_maintained_list.append("True")
            else:
                is_maintained_list.append("False")

    elif level in ["project", "community"]:
        for repo in git_repos_list:
            query_git_commit_i = get_uuid_count_query("cardinality", [repo], "hash",from_date=date-timedelta(days=30), to_date=date)
            commit_frequency_i = client.search(index=git_index, body=query_git_commit_i)['aggregations']["count_of_uuid"]['value']
            if commit_frequency_i > 0:
                is_maintained_list.append("True")
            else:
                is_maintained_list.append("False")

    try:
        is_maintained = is_maintained_list.count("True") / len(is_maintained_list)
    except ZeroDivisionError:
        is_maintained = 0
    result = {
        'is_maintained': round(is_maintained, 4)
    }
    return result


def commit_pr_linked_ratio(client, contributors_index, git_index, pr_index, date, repos_list):
    """ Determine the percentage of new code commit link pull request in the last 90 days """
    code_commit_count = commit_count(client, contributors_index, date, repos_list)["commit_count"]
    code_commit_pr_linked_count = commit_pr_linked_count(client, git_index, pr_index, date, repos_list)["commit_pr_linked_count"]

    result = {
        'commit_pr_linked_ratio': code_commit_pr_linked_count/code_commit_count if code_commit_count > 0 else None
    }
    return result


def commit_count(client, contributors_index, date, repo_list):
    """ Determine the number of commits in the past 90 days. """
    from_date = date - timedelta(days=90)
    to_date = date
    commit_contributor_list = get_contributor_list(client, contributors_index, from_date, to_date, repo_list,
                                                   "code_commit_date_list")
    result = {
        'commit_count': get_commit_count(from_date, to_date, commit_contributor_list),
        'commit_count_bot': get_commit_count(from_date, to_date, commit_contributor_list, is_bot=True),
        'commit_count_without_bot': get_commit_count(from_date, to_date, commit_contributor_list, is_bot=False)
    }
    return result


def commit_pr_linked_count(client, git_index, pr_index, date, repos_list):
    """ Determine the numbers of new code commit link pull request in the last 90 days. """
    repo_git_list = [repo+".git" for repo in repos_list]
    commit_message_list = get_message_list(client, git_index, date - timedelta(days=90), date, repo_git_list)
    commit_hash_set = {message["hash"] for message in commit_message_list}
    commit_hash_list = list(commit_hash_set)
    if len(commit_hash_list) == 0:
        return {'commit_pr_linked_count': 0}
    sub_commit_hash_list = np.array_split(commit_hash_list, math.ceil(len(commit_hash_list) / 100))
    pr_commits_data_set = set()
    for sublist in sub_commit_hash_list:
        pr_message_query = get_message_list_query(field="commits_data", field_values=list(sublist), size=100)
        pr_message_list = client.search(index=pr_index, body=pr_message_query)['hits']['hits']
        for pr_message in pr_message_list:
            pr_commits_data_set = pr_commits_data_set.union(set(pr_message['_source']['commits_data']))
    linked_count = commit_hash_set & pr_commits_data_set

    result = {
        'commit_pr_linked_count': len(linked_count)
    }
    return result


def lines_of_code_frequency(client, git_index, date, repos_list):
    """ Determine the average number of lines touched (lines added plus lines removed) per week in the past 90 """
    result = {
        "lines_of_code_frequency": LOC_frequency(client, git_index, date, repos_list, 'lines_changed')
    }
    return result


def lines_add_of_code_frequency(client, git_index, date, repos_list):
    """ Determine the average number of lines touched (lines added) per week in the past 90 """
    result = {
        "lines_add_of_code_frequency": LOC_frequency(client, git_index, date, repos_list, 'lines_added')
    }
    return result


def lines_remove_of_code_frequency(client, git_index, date, repos_list):
    """ Determine the average number of lines touched (lines removed) per week in the past 90 """
    result = {
        "lines_remove_of_code_frequency": LOC_frequency(client, git_index, date, repos_list, 'lines_removed')
    }
    return result


def get_commit_count(from_date, to_date, contributor_list, company=None, is_bot=None):
    from_date_str = from_date.strftime("%Y-%m-%d")
    to_date_str = to_date.strftime("%Y-%m-%d")
    commit_count = 0
    for contributor in contributor_list:
        if is_bot is None or contributor["is_bot"] == is_bot:
            if company is None:
                for commit_date in contributor["code_commit_date_list"]:
                    if from_date_str <= commit_date <= to_date_str:
                        commit_count += 1
            else:
                for org in contributor["org_change_date_list"]:
                    if org.get("org_name") is not None and org.get("org_name") == company and \
                            check_times_has_overlap(org["first_date"], org["last_date"], from_date_str, to_date_str):
                        for commit_date in contributor["code_commit_date_list"]:
                            if get_latest_date(from_date_str, org["first_date"]) <= commit_date < \
                                    get_oldest_date(org["last_date"], to_date_str):
                                commit_count += 1
    return commit_count


def LOC_frequency(client, git_index, date, repos_list, field='lines_changed'):
    """ Determine the average number of lines touched per week in the past 90 """
    git_repos_list = [repo_url+'.git' for repo_url in repos_list]
    query_LOC_frequency = get_uuid_count_query(
        'sum', git_repos_list, field, 'grimoire_creation_date', size=0, from_date=date-timedelta(days=90), to_date=date)
    loc_frequency = client.search(index=git_index, body=query_LOC_frequency)[
        'aggregations']['count_of_uuid']['value']
    return loc_frequency/12.85



def get_message_list(client, index_name, from_date, to_date, repo_list):
    """ Getting a list of message data in the from_date,to_date time period. """
    result_list = []
    search_after = []
    while True:
        query = get_message_list_query(field_values=repo_list, size=500, from_date=from_date, to_date=to_date,
                                       search_after=search_after)
        message_list = client.search(index=index_name, body=query)["hits"]["hits"]
        if len(message_list) == 0:
            break
        search_after = message_list[len(message_list) - 1]["sort"]
        result_list = result_list + [message["_source"] for message in message_list]
    return result_list