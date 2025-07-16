from io import BytesIO
import os
import tarfile
import hashlib
from urllib.error import URLError

from .vcs_base import load_url
from .vcs_base import test_url
from .vcs_base import download_url_to_file
from .vcs_base import VcsClientBase
from ..util import rmtree


class TarClient(VcsClientBase):

    type = 'tar'

    @staticmethod
    def is_repository(path):
        return False

    def __init__(self, path):
        super(TarClient, self).__init__(path)

    def _calculate_file_hash(self, filepath, hash_type='md5'):
        """Calculate hash of a file"""
        hash_obj = hashlib.new(hash_type)
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()

    def _verify_file_hash(self, filepath, expected_hash, hash_type='md5'):
        """Verify file hash against expected hash"""
        if not expected_hash:
            return True

        actual_hash = self._calculate_file_hash(filepath, hash_type)
        match = actual_hash.lower() == expected_hash.lower()
        if not match:
            print(f"Hash mismatch for {filepath}: {actual_hash} != {expected_hash}")
        return match

    def _get_tarball_path(self, url):
        """Get local path for tarball based on URL"""
        # Extract filename from URL
        filename = url.split('/')[-1]
        if not filename or '?' in filename:
            # Fallback: use URL hash as filename
            import hashlib
            filename = hashlib.md5(url.encode()).hexdigest() + '.tar'

        # Store directly in self.path
        return os.path.join(self.path, filename)

    def import_(self, command):
        if not command.url:
            return {
                'cmd': '',
                'cwd': self.path,
                'output': "Repository data lacks the 'url' value",
                'returncode': 1
            }

        # Get local tarball path first
        tarball_path = self._get_tarball_path(command.url)
        tarball_filename = os.path.basename(tarball_path)

        # clear destination, but preserve the tarball file
        if os.path.exists(self.path):
            for filename in os.listdir(self.path):
                # Skip the tarball file to preserve it for re-extraction
                if filename == tarball_filename:
                    continue
                path = os.path.join(self.path, filename)
                try:
                    rmtree(path)
                except OSError:
                    os.remove(path)
        else:
            not_exist = self._create_path()
            if not_exist:
                return not_exist

        # Check if file exists and verify hash if provided
        file_exists = os.path.exists(tarball_path)
        hash_verified = False

        if file_exists:
            # Verify hash if provided
            if command.hash_md5:
                hash_verified = self._verify_file_hash(tarball_path, command.hash_md5, 'md5')
                if not hash_verified:
                    # Hash mismatch, remove file and re-download
                    os.remove(tarball_path)
                    file_exists = False
            elif command.hash_sha256:
                hash_verified = self._verify_file_hash(tarball_path, command.hash_sha256, 'sha256')
                if not hash_verified:
                    # Hash mismatch, remove file and re-download
                    os.remove(tarball_path)
                    file_exists = False
            else:
                # No hash provided, assume file is valid
                hash_verified = True

        # print(f"Tarball path: {tarball_path} exists: {file_exists} hash_verified: {hash_verified}") 
        # Download tarball if needed
        new_download = False
        if not file_exists or not hash_verified:
            try:
                download_url_to_file(command.url, tarball_path, timeout=10)
            except (URLError, OSError) as e:
                return {
                    'cmd': '',
                    'cwd': self.path,
                    'output':
                        "Could not download tarball from '%s': %s" % (command.url, e),
                    'returncode': 1
                }

            # Verify hash after download if provided
            if command.hash_md5:
                if not self._verify_file_hash(tarball_path, command.hash_md5, 'md5'):
                    return {
                        'cmd': '',
                        'cwd': self.path,
                        'output':
                            "Hash verification failed for tarball from '%s': MD5 mismatch" % command.url,
                        'returncode': 1
                    }
            elif command.hash_sha256:
                if not self._verify_file_hash(tarball_path, command.hash_sha256, 'sha256'):
                    return {
                        'cmd': '',
                        'cwd': self.path,
                        'output':
                            "Hash verification failed for tarball from '%s': SHA256 mismatch" % command.url,
                        'returncode': 1
                    }
            new_download = True

        # Extract tarball from file
        try:
            tar = tarfile.open(tarball_path, mode='r', errorlevel=1)
        except (tarfile.ReadError, IOError, OSError) as e:
            return {
                'cmd': '',
                'cwd': self.path,
                'output':
                    "Failed to read tarball file '%s': %s" % (tarball_path, e),
                'returncode': 1
            }

        if not command.version:
            members = None
        else:
            # remap all members from version subfolder into destination
            def get_members(tar, prefix):
                for tar_info in tar.getmembers():
                    if tar_info.name.startswith(prefix):
                        tar_info.name = tar_info.name[len(prefix):]
                        yield tar_info
            prefix = str(command.version) + '/'
            members = get_members(tar, prefix)

        tar.extractall(self.path, members)
        tar.close()

        return {
            'cmd': '',
            'cwd': self.path,
            'output':
                "Downloaded tarball ({}) from '{}' and unpacked it".format(
                    "new" if new_download else "existing",
                    command.url
            'output': output_msg,
            'returncode': 0,
            'is_raw_file': is_raw_file
        }

    def validate(self, command):
        if not command.url:
            return {
                'cmd': '',
                'cwd': self.path,
                'output': "Repository data lacks the 'url' value",
                'returncode': 1
            }

        # test remote url
        try:
            test_url(command.url, retry=command.retry)
        except URLError as e:
            return {
                'cmd': '',
                'cwd': self.path,
                'output':
                    "Failed to contact tarball url '%s': %s" %
                    (command.url, e),
                'returncode': 1
            }

        # test local tarball and hash
        tarball_path = self._get_tarball_path(command.url)
        local_status = "Local tarball not found"

        if os.path.exists(tarball_path):
            local_status = "Local tarball exists"

            # Verify hash if provided
            if command.hash_md5:
                if self._verify_file_hash(tarball_path, command.hash_md5, 'md5'):
                    local_status += " and MD5 hash verified"
                else:
                    return {
                        'cmd': '',
                        'cwd': self.path,
                        'output':
                            "Local tarball exists but MD5 hash verification failed for '%s'" % command.url,
                        'returncode': 1
                    }
            elif command.hash_sha256:
                if self._verify_file_hash(tarball_path, command.hash_sha256, 'sha256'):
                    local_status += " and SHA256 hash verified"
                else:
                    return {
                        'cmd': '',
                        'cwd': self.path,
                        'output':
                            "Local tarball exists but SHA256 hash verification failed for '%s'" % command.url,
                        'returncode': 1
                    }
            else:
                local_status += " (no hash verification)"
        else:
            local_status += " - will be downloaded on import"

        return {
            'cmd': 'http HEAD url',
            'cwd': self.path,
            'output': "Tarball url '%s' exists. %s" % (command.url, local_status),
            'returncode': None
        }
