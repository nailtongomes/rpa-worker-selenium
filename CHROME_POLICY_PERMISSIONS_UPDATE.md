# Chrome Policy Directory Permissions Update

## Issue
Users needed permission to write to `/etc/opt/chrome/policies/managed/auto_select_certificate.json` for digital certificate and PJeOffice integration without requiring sudo.

## Solution
Changed the ownership of the Chrome policy directory to `rpauser` instead of using world-writable permissions.

## Changes Made

### Dockerfiles

#### 1. Dockerfile (Main Chrome-based image)
- **Line 194-198**: Added ownership change for Chrome policy directory
  ```dockerfile
  RUN mkdir -p /etc/opt/chrome/policies/managed \
      && chown -R rpauser:rpauser /etc/opt/chrome/policies/managed \
      && chmod 755 /etc/opt/chrome/policies/managed
  ```
- **Line 153-154**: Updated comment to reflect new permissions model

#### 2. Dockerfile.trixie (Debian Trixie-based)
- **Line 229-233**: Added Chrome policy directory creation with rpauser ownership
  ```dockerfile
  RUN mkdir -p /etc/opt/chrome/policies/managed \
      && chown -R rpauser:rpauser /etc/opt/chrome/policies/managed \
      && chmod 755 /etc/opt/chrome/policies/managed
  ```

#### 3. Dockerfile.alpine
- **Line 103-107**: Added Chrome/Chromium policy directory (root only, no rpauser)
  ```dockerfile
  RUN mkdir -p /etc/opt/chrome/policies/managed \
      && chmod 755 /etc/opt/chrome/policies/managed
  ```

### Documentation

#### A1_CERTIFICATE_GUIDE.md
- Removed all `sudo` commands from certificate management examples
- Updated `write_chrome_policy()` function to write directly to the policy file
- Updated `cleanup_chrome_policy()` function to remove file directly
- Added note that the Chrome policy directory is owned by rpauser

#### example_cert_management.py
- Removed `sudo` usage for writing Chrome policy files
- Changed from using temporary files + sudo mv to direct file writes
- Updated cleanup function to use `os.remove()` instead of `sudo rm`
- Added better error handling for permission issues

## Security Considerations

### Why not 777 permissions?
World-writable (`777`) permissions were initially considered but rejected because:
- Security risk: Any process can write to the directory
- Not following principle of least privilege
- Could allow malicious code to inject policies

### Why ownership-based approach?
Setting ownership to `rpauser:rpauser` with `755` permissions:
- ✅ Secure: Only owner (rpauser) and root can write
- ✅ Compatible: Works when running as root or rpauser
- ✅ Simple: No sudo required for certificate management
- ✅ Standard: Follows Linux permission best practices

## Benefits

1. **No sudo required**: Certificate management code is simpler and cleaner
2. **Works for both users**: Root can write (bypasses ownership), rpauser can write (as owner)
3. **Better security**: Not world-writable, follows principle of least privilege
4. **Easier integration**: PJeOffice and certificate workflows work seamlessly

## Testing

A test script has been added: `test_chrome_policy_permissions.py`

Run it inside a built container:
```bash
# Test as root
docker run --rm rpa-worker-selenium python /app/test_chrome_policy_permissions.py

# Test as rpauser
docker run --rm --user rpauser rpa-worker-selenium python /app/test_chrome_policy_permissions.py
```

The test verifies:
- Directory exists
- Correct permissions and ownership
- Write access works
- Policy file can be created and removed
- No sudo is required

## Backward Compatibility

- Existing code using `sudo` will still work (rpauser has sudo access)
- New code can write directly without sudo
- Container still runs as root by default
- Non-root users can now write to the policy directory

## Related Files

- `Dockerfile` - Main Chrome-based image
- `Dockerfile.trixie` - Debian Trixie-based image with Chrome support
- `Dockerfile.alpine` - Alpine-based image with Chromium
- `A1_CERTIFICATE_GUIDE.md` - Certificate management guide
- `example_cert_management.py` - Certificate management example
- `test_chrome_policy_permissions.py` - Permission verification test
