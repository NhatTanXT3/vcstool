import os
import socket
import subprocess
import time
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen


class VcsClientBase(object):

    type = None

    def __init__(self, path):
        self.path = path

    def __getattribute__(self, name):
        if name == 'import':
            try:
                return self.import_
            except AttributeError:
                pass
        return super(VcsClientBase, self).__getattribute__(name)

    def _not_applicable(self, command, message=None):
        return {
            'cmd': '%s.%s(%s)' % (
                self.__class__.type, 'push', command.__class__.command),
            'output': "Command '%s' not applicable for client '%s'%s" % (
                command.__class__.command, self.__class__.type,
                ': ' + message if message else ''),
            'returncode': NotImplemented
        }

    def _run_command(self, cmd, env=None, retry=0):
        for i in range(retry + 1):
            result = run_command(cmd, os.path.abspath(self.path), env=env)
            if not result['returncode']:
                # return successful result
                break
            if i >= retry:
                # return the failure after retries
                break
            # increasing sleep before each retry
            time.sleep(i + 1)
        return result

    def _create_path(self):
        if not os.path.exists(self.path):
            try:
                os.makedirs(self.path)
            except os.error as e:
                return {
                    'cmd': 'os.makedirs(%s)' % self.path,
                    'cwd': self.path,
                    'output':
                        "Could not create directory '%s': %s" % (self.path, e),
                    'returncode': 1
                }
        return None


def run_command(cmd, cwd, env=None):
    if not os.path.exists(cwd):
        cwd = None
    result = {'cmd': ' '.join(cmd), 'cwd': cwd}
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env)
        output, _ = proc.communicate()
        result['output'] = output.rstrip().decode('utf8')
        result['returncode'] = proc.returncode
    except subprocess.CalledProcessError as e:
        result['output'] = e.output.decode('utf8')
        result['returncode'] = e.returncode
    return result


def load_url(url, retry=2, retry_period=1, timeout=10):
    try:
        fh = urlopen(url, timeout=timeout)
    except HTTPError as e:
        if e.code == 503 and retry:
            time.sleep(retry_period)
            return load_url(
                url, retry=retry - 1, retry_period=retry_period,
                timeout=timeout)
        e.msg += ' (%s)' % url
        raise
    except URLError as e:
        if isinstance(e.reason, socket.timeout) and retry:
            time.sleep(retry_period)
            return load_url(
                url, retry=retry - 1, retry_period=retry_period,
                timeout=timeout)
        raise URLError(str(e) + ' (%s)' % url)
    return fh.read()


def test_url(url, retry=2, retry_period=1, timeout=10):
    request = Request(url)
    request.get_method = lambda: 'HEAD'

    try:
        response = urlopen(request)
    except HTTPError as e:
        if e.code == 503 and retry:
            time.sleep(retry_period)
            return test_url(
                url, retry=retry - 1, retry_period=retry_period,
                timeout=timeout)
        e.msg += ' (%s)' % url
        raise
    except URLError as e:
        if isinstance(e.reason, socket.timeout) and retry:
            time.sleep(retry_period)
            return test_url(
                url, retry=retry - 1, retry_period=retry_period,
                timeout=timeout)
        raise URLError(str(e) + ' (%s)' % url)
    return response


def download_url_to_file(url, filepath, timeout=10, chunk_size=8192):
    """
    Download a file from URL to filepath using streaming for memory efficiency.
    Shows progress during download.

    Args:
        url: The URL to download from
        filepath: The local file path to save to
        timeout: Connection timeout in seconds
        chunk_size: Size of chunks to read at once (default: 8KB)

    Raises:
        URLError: If download fails
        OSError: If file operations fail
    """
    import sys

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    try:
        # Open URL connection
        response = urlopen(url, timeout=timeout)

        # Get total file size if available
        total_size = response.headers.get('Content-Length')
        if total_size:
            total_size = int(total_size)

        # Open file for writing
        with open(filepath, 'wb') as f:
            downloaded = 0
            start_time = time.time()
            last_progress_time = start_time
            progress_interval = 1.0  # Show progress every 1 second

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break

                f.write(chunk)
                downloaded += len(chunk)

                # Show progress periodically
                current_time = time.time()
                if current_time - last_progress_time >= progress_interval:
                    elapsed = current_time - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0

                    # Format progress message
                    if total_size:
                        percentage = (downloaded / total_size) * 100
                        progress_msg = "Downloading {} : {:.1f}MB / {:.1f}MB ({:.0f}%) - {:.1f}KB/s".format(
                            url,
                            downloaded / (1024 * 1024),
                            total_size / (1024 * 1024),
                            percentage,
                            speed / 1024
                        )
                    else:
                        progress_msg = "Downloading {} : {:.1f}MB - {:.1f}KB/s".format(
                            url,
                            downloaded / (1024 * 1024),
                            speed / 1024
                        )

                    # Print progress (with carriage return to overwrite line)
                    print(progress_msg, end='\r', file=sys.stderr)
                    last_progress_time = current_time

            # Final progress message
            elapsed = time.time() - start_time
            speed = downloaded / elapsed if elapsed > 0 else 0

            if total_size:
                percentage = (downloaded / total_size) * 100
                final_msg = "Downloaded {} : {:.1f}MB / {:.1f}MB ({:.0f}%) - {:.1f}KB/s".format(
                    url,
                    downloaded / (1024 * 1024),
                    total_size / (1024 * 1024),
                    percentage,
                    speed / 1024
                )
            else:
                final_msg = "Downloaded {} : {:.1f}MB - {:.1f}KB/s".format(
                    url,
                    downloaded / (1024 * 1024),
                    speed / 1024
                )

            print(final_msg, file=sys.stderr)

    except HTTPError as e:
        e.msg += ' (%s)' % url
        raise
    except URLError as e:
        raise URLError(str(e) + ' (%s)' % url)
    except OSError as e:
        raise OSError("Failed to write file '%s': %s" % (filepath, e))
