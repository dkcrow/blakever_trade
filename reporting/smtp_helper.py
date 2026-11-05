# -*- coding: utf-8 -*-
"""SMTP发送共享模块: 465 SSL失败时自动兜底587 STARTTLS。

背景: 2026-10-13起 smtp.qq.com:465 隐式TLS出现 SSL WRONG_VERSION_NUMBER,
587 STARTTLS 路径正常。所有邮件发送统一走本模块兜底。
"""
import smtplib


def send_message(msg, server="smtp.qq.com", sender=None, receiver=None, password=None, timeout=30):
    """发送email.mime消息, 465 SSL优先, 失败兜底587 STARTTLS。

    返回: (True, 'ssl'|'starttls') 或抛出最后一个异常。
    """
    last_err = None
    # 路径1: 465 隐式SSL
    try:
        with smtplib.SMTP_SSL(server, 465, timeout=timeout) as s:
            s.login(sender, password)
            s.sendmail(sender, receiver, msg.as_string())
        return True, "ssl"
    except Exception as e:
        last_err = e
        print(f"[SMTP] 465 SSL failed ({e}), fallback to 587 STARTTLS")
    # 路径2: 587 STARTTLS
    try:
        with smtplib.SMTP(server, 587, timeout=timeout) as s:
            s.ehlo()
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, receiver, msg.as_string())
        return True, "starttls"
    except Exception as e:
        last_err = e
    raise last_err
