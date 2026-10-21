from __future__ import annotations

from dataclasses import dataclass

from .logging_setup import sanitize_text

ERROR_CODES = (
    "CANCELLED",
    "INVALID_URL",
    "UNSUPPORTED_URL",
    "EXTRACTOR_OUTDATED",
    "AUTH_REQUIRED",
    "ACCESS_DENIED",
    "GEO_BLOCKED",
    "PRIVATE_VIDEO",
    "NOT_FOUND",
    "RATE_LIMITED",
    "NETWORK",
    "TIMEOUT",
    "FORMAT_UNAVAILABLE",
    "FFMPEG_MISSING",
    "FFMPEG_ERROR",
    "DISK_FULL",
    "PERMISSION",
    "PATH_INVALID",
    "DRM_UNSUPPORTED",
    "POSTPROCESSING",
    "LIVE_UNSUPPORTED",
    "UNKNOWN",
)


@dataclass(frozen=True)
class Diagnosis:
    code: str
    title: str
    summary: str
    remedy: str
    technical: str = ""
    retryable: bool = True
    open_logs: bool = True

    @property
    def is_cancel(self) -> bool:
        return self.code == "CANCELLED"


def _diagnosis(
    code: str,
    title: str,
    summary: str,
    remedy: str,
    technical: str,
    *,
    retryable: bool = True,
) -> Diagnosis:
    return Diagnosis(
        code=code,
        title=title,
        summary=summary,
        remedy=remedy,
        technical=sanitize_text(technical, 4000),
        retryable=retryable,
    )


def classify_error(error: BaseException | str, *, stage: str = "download") -> Diagnosis:
    raw = sanitize_text(str(error), 4000)
    text = raw.lower()
    technical = raw
    if isinstance(error, BaseException) and error.__class__.__name__ in {
        "DownloadCancelled",
        "DownloadPaused",
        "AnalysisCancelled",
    }:
        return _diagnosis(
            "CANCELLED",
            "処理を中止しました",
            "ダウンロードはキャンセルされました。",
            "必要に応じて、もう一度ダウンロードを開始してください。",
            technical,
            retryable=True,
        )

    patterns: list[tuple[str, tuple[str, ...]]] = [
        (
            "DISK_FULL",
            (
                "no space left",
                "not enough space",
                "disk full",
                "errno 28",
                "ディスク容量",
            ),
        ),
        (
            "FFMPEG_MISSING",
            (
                "ffmpeg not found",
                "ffmpeg is not installed",
                "ffmpeg not installed",
                "ffprobe not found",
                "you have requested merging",
                "ffmpeg location",
                "ffmpeg が見つかりません",
                "ffmpeg が必要です",
            ),
        ),
        (
            "DRM_UNSUPPORTED",
            (
                "drm",
                "digital rights management",
                "protected content",
                "encrypted media",
            ),
        ),
        (
            "GEO_BLOCKED",
            (
                "not available in your country",
                "available in your country",
                "geo restriction",
                "geo-restricted",
                "geo blocked",
                "geo-blocked",
                "geoblock",
                "geoblocking",
                "region locked",
                "this video is not available in your country",
                "not available from your location",
                "blocked it in your country",
            ),
        ),
        (
            "PRIVATE_VIDEO",
            (
                "private video",
                "this video is private",
                "video is private",
                "members-only",
                "members only",
                "join this channel",
            ),
        ),
        (
            "AUTH_REQUIRED",
            (
                "sign in to confirm",
                "please sign in",
                "login required",
                "log in to",
                "requires authentication",
                "authentication required",
                "cookies",
                "not a bot",
                "confirm you’re not a bot",
                "confirm you're not a bot",
                "account credentials",
            ),
        ),
        (
            "ACCESS_DENIED",
            (
                "http error 403",
                "403 forbidden",
                "http error 401",
                "unauthorized",
                "access denied",
                "forbidden",
                "age-restricted",
                "age restricted",
                "confirm your age",
            ),
        ),
        (
            "NOT_FOUND",
            (
                "http error 404",
                "404 not found",
                "video unavailable",
                "this video does not exist",
                "has been removed",
                "removed by the uploader",
                "content is not available",
            ),
        ),
        (
            "RATE_LIMITED",
            (
                "http error 429",
                "too many requests",
                "rate limit",
                "rate-limit",
            ),
        ),
        (
            "FORMAT_UNAVAILABLE",
            (
                "requested format is not available",
                "requested format not available",
                "format is not available",
            ),
        ),
        (
            "LIVE_UNSUPPORTED",
            (
                "is live",
                "live event",
                "live stream",
                "premieres in",
            ),
        ),
        (
            "POSTPROCESSING",
            (
                "postprocessing",
                "post-process",
                "ffmpeg exited with code",
                "conversion failed",
                "merging of multiple formats",
                "unable to merge",
                "fixup",
            ),
        ),
        (
            "TIMEOUT",
            (
                "timed out",
                "timeout",
                "read operation timed out",
            ),
        ),
        (
            "NETWORK",
            (
                "connection reset",
                "connection refused",
                "connection aborted",
                "failed to resolve",
                "getaddrinfo",
                "name or service not known",
                "temporary failure in name resolution",
                "network is unreachable",
                "ssl",
                "certificate verify failed",
                "unable to download webpage",
                "urlopen error",
                "proxy",
                "remote end closed connection",
                "ホスト名を解決できません",
            ),
        ),
        (
            "PERMISSION",
            (
                "permission denied",
                "access is denied",
                "errno 13",
                "privilege",
                "read-only file system",
            ),
        ),
        (
            "PATH_INVALID",
            (
                "filename too long",
                "path too long",
                "invalid filename",
                "no such file or directory",
                "cannot create directory",
                "the filename",
                "cannot save",
            ),
        ),
        (
            "UNSUPPORTED_URL",
            (
                "unsupported url",
                "no suitable extractor",
                "no extractor",
                "unsupported site",
            ),
        ),
        (
            "EXTRACTOR_OUTDATED",
            (
                "unable to extract",
                "failed to extract",
                "extractor",
                "no video formats",
                "no video formats found",
                "no formats found",
                "signature extraction failed",
                "nsig extraction failed",
                "player response",
                "unable to download api page",
                "unable to extract webpage",
            ),
        ),
        (
            "INVALID_URL",
            (
                "is not a valid url",
                "invalid url",
                "not a valid url",
                "no video id",
                "url could not be interpreted",
                "url を入力してください",
                "url に空白",
                "url を解釈",
                "認証情報を含める",
                "ローカルネットワーク",
                "内部サービス上",
            ),
        ),
    ]
    for code, needles in patterns:
        if any(needle in text for needle in needles):
            return _make_diagnosis(code, technical, stage=stage)
    if "cancelled" in text or "canceled" in text:
        return _make_diagnosis("CANCELLED", technical, stage=stage)
    return _make_diagnosis("UNKNOWN", technical, stage=stage)


def _make_diagnosis(code: str, technical: str, *, stage: str) -> Diagnosis:
    stage_label = {
        "analysis": "解析",
        "download": "ダウンロード",
        "postprocess": "ファイル処理",
        "update": "更新",
    }.get(stage, "処理")
    table: dict[str, tuple[str, str, str, bool]] = {
        "CANCELLED": (
            "処理を中止しました",
            f"{stage_label}はキャンセルされました。",
            "必要に応じて、もう一度開始してください。",
            True,
        ),
        "INVALID_URL": (
            "URL を確認してください",
            "入力された URL を動画ページとして解釈できませんでした。",
            "ブラウザーで動画を開き、アドレスバーから URL をコピーし直してください。URL の代わりに検索キーワードが入力されていないかも確認してください。",
            True,
        ),
        "UNSUPPORTED_URL": (
            "このサイトはまだ対応していません",
            "URL に対応する抽出機能（Extractor）が見つかりませんでした。",
            "yt-dlp を最新版に更新すると対応する場合があります。診断画面の「yt-dlp を更新」を確認してください。",
            False,
        ),
        "EXTRACTOR_OUTDATED": (
            "サイトの仕様が変わった可能性があります",
            "動画ページの構造を読み取れませんでした。サイト側の変更や一時的な制限が原因のことがあります。",
            "診断画面で yt-dlp を最新版に更新してから、もう一度お試しください。改善しない場合は、URL とログを添えて報告してください。",
            True,
        ),
        "AUTH_REQUIRED": (
            "ログインが必要です",
            "この動画はログインや年齢確認などの認証を求めています。",
            "自分が利用権を持つアカウントの Cookie ファイル（Netscape 形式）を設定画面で指定してください。他人の Cookie は使用しないでください。",
            True,
        ),
        "ACCESS_DENIED": (
            "アクセスが制限されています",
            "サーバーがダウンロードを拒否しました（403 など）。地域制限、非公開設定、年齢制限、一時的なブロックが考えられます。",
            "ブラウザーで動画を再生できるか確認し、必要なら Cookie を設定してください。時間を置いて再試行すると成功する場合もあります。",
            True,
        ),
        "GEO_BLOCKED": (
            "地域制限されています",
            "この動画は現在の地域では配信されていません。",
            "配信が許可されている地域や公式サービスから視聴してください。地域制限の回避は本アプリでは行いません。",
            False,
        ),
        "PRIVATE_VIDEO": (
            "非公開またはメンバー限定の動画です",
            "動画が非公開、削除済み、またはメンバー限定に設定されています。",
            "動画の公開設定を確認してください。自分がアクセス権を持つ場合は Cookie を設定すると取得できる場合があります。",
            False,
        ),
        "NOT_FOUND": (
            "動画が見つかりません",
            "URL が間違っているか、動画が削除・移動された可能性があります。",
            "ブラウザーで URL を開き直し、最新の URL をコピーしてください。",
            False,
        ),
        "RATE_LIMITED": (
            "アクセスが集中しています",
            "サーバーから回数制限（429）を受け取りました。",
            "しばらく待ってから再試行してください。同時ダウンロード数を設定画面で減らすと改善することがあります。",
            True,
        ),
        "NETWORK": (
            "ネットワークに接続できません",
            "接続が切断されたか、DNS 解決・SSL 通信に失敗しました。",
            "インターネット接続、VPN、プロキシ、ファイアウォールの設定を確認して再試行してください。",
            True,
        ),
        "TIMEOUT": (
            "接続がタイムアウトしました",
            "サーバーから一定時間応答がありませんでした。",
            "接続状況を確認し、時間を置いて再試行してください。VPN やプロキシを使用している場合は設定を見直してください。",
            True,
        ),
        "FORMAT_UNAVAILABLE": (
            "選択した画質・形式を利用できません",
            "この動画では指定した形式が配信されていないか、選択肢が変わっています。",
            "ホーム画面で動画を再解析し、表示された形式から選び直してください。「最高画質（自動）」を選ぶと失敗しにくくなります。",
            True,
        ),
        "FFMPEG_ERROR": (
            "ファイルの変換・結合に失敗しました",
            "FFmpeg の処理中にエラーが発生しました。",
            "別の形式（MP4 など）を選ぶか、保存先の空き容量を確認してください。詳細は診断ログに記録されています。",
            True,
        ),
        "FFMPEG_MISSING": (
            "FFmpeg が見つかりません",
            "映像と音声の結合や音声変換に必要な FFmpeg が見つかりませんでした。",
            "同梱の FFmpeg が壊れている場合は再インストールしてください。診断画面で検出状況を確認できます。",
            False,
        ),
        "DISK_FULL": (
            "保存先の空き容量が不足しています",
            "ダウンロード中にディスクの空き容量がなくなりました。",
            "不要なファイルを削除するか、別のドライブを保存先に設定して再試行してください。",
            True,
        ),
        "PERMISSION": (
            "保存先に書き込めません",
            "フォルダーの書き込み権限がないか、ファイルが他のアプリで使用されています。",
            "書き込み可能なフォルダーを保存先に選ぶか、Windows の権限設定を確認してください。",
            True,
        ),
        "PATH_INVALID": (
            "ファイル名またはパスに問題があります",
            "ファイル名が長すぎるか、使用できない文字が含まれています。",
            "設定のファイル名テンプレートを短くするか、保存先を浅い階層のフォルダーに変更してください。",
            True,
        ),
        "DRM_UNSUPPORTED": (
            "DRM で保護されたコンテンツです",
            "この動画は著作権保護（DRM）が有効なため、ダウンロードできません。",
            "DRM の解除は行いません。公式アプリや配信サービスを利用してください。",
            False,
        ),
        "POSTPROCESSING": (
            "ダウンロード後の処理に失敗しました",
            "映像と音声の結合、または音声の変換に失敗しました。",
            "FFmpeg の検出状況を診断画面で確認してください。別の形式を選ぶと成功する場合があります。",
            True,
        ),
        "LIVE_UNSUPPORTED": (
            "ライブ配信は完全には対応していません",
            "ライブ配信やプレミア公開は、配信状況によって保存できない場合があります。",
            "配信終了後に再試行するか、アーカイブが公開されてからダウンロードしてください。",
            True,
        ),
        "UNKNOWN": (
            "処理を完了できませんでした",
            "予期しないエラーが発生しました。",
            "もう一度試しても解決しない場合は、診断画面でログを確認し、エラー内容を添えて報告してください。",
            True,
        ),
    }
    title, summary, remedy, retryable = table[code]
    if stage == "analysis" and code in {"NETWORK", "TIMEOUT"}:
        summary = "動画情報を取得できませんでした。" + summary
    return Diagnosis(
        code=code,
        title=title,
        summary=summary,
        remedy=remedy,
        technical=technical,
        retryable=retryable,
    )


def friendly_error(error: BaseException | str, *, stage: str = "download") -> str:
    diagnosis = classify_error(error, stage=stage)
    return f"{diagnosis.title}: {diagnosis.summary}"
