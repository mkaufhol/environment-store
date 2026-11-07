# Deploying with encrypted stores

A deployed app has to read its encrypted stores without anyone typing a key. This guide shows how to hand the key
over on Heroku, on Kubernetes, and in other containers or CI systems: as the environment variable
`ENV_STORE_KEY_<STORE>`, or as a mounted key file passed with `-k` or `[keys]`. It ends with what encryption still
protects once the key sits in the deployment's configuration, and how to rotate the key.

The `envs` commands and their output on this page were run against the real CLI. The Heroku, Kubernetes, Docker and
CI snippets could not be run for this guide; they use only standard commands and fields, but adapt them to your
setup.

- [Two ways to hand over the key](#two-ways-to-hand-over-the-key)
- [The key variable `ENV_STORE_KEY_<STORE>`](#the-key-variable-env_store_key_store)
- [The key is already text: no base64 needed](#the-key-is-already-text-no-base64-needed)
- [Heroku](#heroku)
- [Kubernetes](#kubernetes)
- [Other containers and CI](#other-containers-and-ci)
- [Security notes](#security-notes)

## Two ways to hand over the key

| | Key variable `ENV_STORE_KEY_<STORE>` | Key file, `-k STORE=PATH` or `[keys]` |
|---|---|---|
| Works on | every platform, including Heroku, which cannot mount files | Kubernetes, Docker, CI systems with secret files |
| Where the key lives at run time | in the environment of the `envs` process (or of your app, with the Python library) | in a file, readable only by the app's user |
| Recommended | when files are not an option | yes: the key stays out of the process environment |

Both work the same for the CLI, the Python library and the TUI. A `-k` given on the command line always wins over
the variable, and the variable wins over `[keys]` in the project file.

The examples use a plain store `base` and a store `prod` encrypted with the key file `prod.key`:

```console
$ export ENV_STORE_CONNECTION=json://envs
$ envs create-store base
created store 'base'
$ envs set -s base DB_HOST=localhost
set DB_HOST in store 'base'
$ envs create-store prod -e --generate-key prod.key
created store 'prod'
$ envs set -s prod -k prod.key DB_PASSWORD < password.txt
set DB_PASSWORD in store 'prod'
```

## The key variable `ENV_STORE_KEY_<STORE>`

`envs`, the Python library and the TUI read an existing store's key or passphrase from the environment variable
`ENV_STORE_KEY_<STORE>`. `<STORE>` is the store name in upper case with `-` turned into `_`:

| Store | Variable |
|---|---|
| `prod` | `ENV_STORE_KEY_PROD` |
| `customer-a` | `ENV_STORE_KEY_CUSTOMER_A` |

The value is what a `-k` file would hold: the key line (`envstore-key-v1:…`, the content of the key file, or the
output of `envs keygen -`) for a key file store, the passphrase for a passphrase store. One trailing newline is
removed.

```console
$ export ENV_STORE_KEY_PROD="$(cat prod.key)"
$ envs --noinput ls base prod -v
DB_HOST=localhost
DB_PASSWORD=hunter2
```

The rules:

- **Order.** `-k` (library: `key=`, `keys=`, `Source(key=…)`) > `ENV_STORE_KEY_<STORE>` > `[keys]` in the project
  file > the hidden prompt. A `-k` therefore beats the variable, and the variable beats `[keys]`.
- **Errors name the variable, never its value.** An empty or malformed value is a key error with exit code 4:

  ```console
  $ ENV_STORE_KEY_PROD= envs --noinput ls prod
  Error: ENV_STORE_KEY_PROD, the key or passphrase of store 'prod', is empty
  $ ENV_STORE_KEY_PROD=nope envs --noinput ls prod
  Error: ENV_STORE_KEY_PROD does not hold a usable key for store 'prod': not a valid key file: expected one line 'envstore-key-v1:<base64url of 32 bytes>'; create one with envs keygen
  ```

  A key that does not fit the store gives the usual decryption error, also exit code 4:

  ```console
  $ ENV_STORE_KEY_PROD="$(cat old.key)" envs --noinput ls prod
  Error: cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified
  ```

- **Ignored when it does not apply.** Variables of stores the command does not use are ignored, and so is the
  variable of a plain store: environments are shared, so it was not set for this command.
- **Two stores, one variable.** `my-app` and `my_app` both map to `ENV_STORE_KEY_MY_APP`. If one command uses both,
  both are encrypted and the variable is set, `envs` cannot tell which store it is for and stops with exit code 1,
  unless `-k` gives the key of both:

  ```console
  $ ENV_STORE_KEY_MY_APP=a envs --noinput ls my-app my_app
  Error: encrypted stores 'my-app', 'my_app' all take their key from ENV_STORE_KEY_MY_APP, so it is unclear which store it is for: unset it and give each of these stores its key explicitly
  ```

- **Only for existing stores.** New keys never come from the environment: `create-store -e`, `encrypt`,
  `rekey --new-key` and the new-key options of `cp-store` / `mv-store` keep their explicit options. The *old* key
  of `rekey` may come from the variable.
- **Not passed on by `envs run`.** See [Security notes](#security-notes).

Without a key from any source, `--noinput` (or a stdin that is not a terminal) makes the command fail at once
instead of waiting for input, and the message names the variable:

```console
$ envs --noinput run base prod -- true
Error: store 'prod' is encrypted and no key or passphrase was given: pass it with -k prod=<path> (or -k prod=- for stdin), or set ENV_STORE_KEY_PROD
```

## The key is already text: no base64 needed

A key file is one line of plain ASCII text, `envstore-key-v1:` followed by the 32 key bytes in base64url. A
passphrase is text too. So put the content of the key file into a config var, a CI secret or a Secret as it is.
Do **not** base64-encode it first: `envs` would not recognise the encoded text.

```console
$ ENV_STORE_KEY_PROD="$(base64 < prod.key)" envs --noinput ls prod
Error: ENV_STORE_KEY_PROD does not hold a usable key for store 'prod': not a valid key file: expected one line 'envstore-key-v1:<base64url of 32 bytes>'; create one with envs keygen
```

The one place where base64 appears is the `data:` field of a Kubernetes Secret manifest: Kubernetes expects it
base64-encoded and decodes it before the container sees it. Write the key into `stringData:` instead, which takes
the text as it is ([below](#kubernetes)), or let `kubectl create secret … --from-file` do the encoding.

## Heroku

Heroku cannot mount a key file into a dyno, so its config vars are the place for the key. Set the connection and
one key variable per encrypted store:

```sh
heroku config:set ENV_STORE_CONNECTION='postgresql://…' ENV_STORE_KEY_PROD="$(cat prod.key)"
```

The app needs the package with the extras it uses, for example `environment-store[cli,postgres]` in its
dependencies (see [Installation](installation.md#optional-extras)).

**With `envs run` in the `Procfile`.** `envs` loads the stores, removes `ENV_STORE_KEY_PROD` from the environment
and starts the server with the variables:

```text
web: envs --noinput run base prod -- gunicorn myproject.wsgi
```

**With the Python library in Django's `settings.py`.** `environment_store.load()` reads `ENV_STORE_CONNECTION`
and `ENV_STORE_KEY_PROD` and puts the variables into `os.environ`; this needs only the `postgres` extra, not `cli`:

```python
# myproject/settings.py
import os

import environment_store

environment_store.load("base", "prod", noinput=True)
# The library leaves os.environ alone apart from the loaded variables; drop the key
# so that subprocesses of the app do not inherit it.
os.environ.pop("ENV_STORE_KEY_PROD", None)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ["DB_HOST"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        # ...
    }
}
```

`noinput=True` makes a missing key raise `KeyRequiredError` instead of prompting. Variables already set as config
vars win over the stores unless you pass `overwrite=True`.

## Kubernetes

### As a mounted file (recommended)

Mount the key from a Secret as a file and pass its path with `-k` (or with `[keys]` in a project file in the
image). The key then never enters the process environment, where every child process and every tool that can read
the environment would see it.

The Secret, with the key text in `stringData` as it is (the connection goes in a second Secret, so that each can
have its own access rules):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: envs-keys
type: Opaque
stringData:
  prod.key: "envstore-key-v1:…"
---
apiVersion: v1
kind: Secret
metadata:
  name: envs-connection
type: Opaque
stringData:
  ENV_STORE_CONNECTION: "postgresql://app:…@db.internal/app"
```

Or create them from the files you already have; `kubectl` does the base64 encoding of `data:` for you:

```sh
kubectl create secret generic envs-keys --from-file=prod.key=prod.key
kubectl create secret generic envs-connection --from-literal=ENV_STORE_CONNECTION='postgresql://…'
```

The pod template of the Deployment mounts the key at `/etc/envs/prod.key` and takes the connection with `envFrom`:

```yaml
spec:
  securityContext:
    runAsUser: 1000
    fsGroup: 1000            # the key file's group, so that the non-root user can read it
  containers:
    - name: app
      image: example/app
      command: ["envs", "--noinput", "run", "base", "prod", "-k", "prod=/etc/envs/prod.key",
                "--", "gunicorn", "myproject.wsgi"]
      envFrom:
        - secretRef:
            name: envs-connection
      volumeMounts:
        - name: envs-keys
          mountPath: /etc/envs
          readOnly: true
  volumes:
    - name: envs-keys
      secret:
        secretName: envs-keys
        defaultMode: 0440
```

With a project file in the image instead of `-k`, the command shrinks to
`["envs", "--noinput", "run", "--", "gunicorn", "myproject.wsgi"]`:

```toml
stores = ["base", "prod"]

[keys]
prod = "/etc/envs/prod.key"
```

The project file must belong to the user that runs `envs` (or to root) and must not be writable by every user,
otherwise it is ignored with a warning ([the trust check](configuration.md#the-trust-check)).

### As an environment variable

If mounting files is not an option, put the key into the environment. Either map one Secret entry to the variable
with `valueFrom`:

```yaml
      env:
        - name: ENV_STORE_KEY_PROD
          valueFrom:
            secretKeyRef:
              name: envs-keys
              key: prod.key
      command: ["envs", "--noinput", "run", "base", "prod", "--", "gunicorn", "myproject.wsgi"]
```

or name the Secret's entries after the variables and take all of them with `envFrom`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: envs-env
type: Opaque
stringData:
  ENV_STORE_CONNECTION: "postgresql://app:…@db.internal/app"
  ENV_STORE_KEY_PROD: "envstore-key-v1:…"
```

```yaml
      envFrom:
        - secretRef:
            name: envs-env
```

Pods read Secrets into environment variables only when they start: after changing a Secret, restart the pods, for
example with `kubectl rollout restart deployment/app`. `envs` reads a mounted key file only at start too.

## Other containers and CI

**Containers.** The same two options work with any container runtime. Make `envs run` the entrypoint, so that
every command the image runs gets the stores:

```dockerfile
ENTRYPOINT ["envs", "--noinput", "run", "base", "prod", "--"]
CMD ["gunicorn", "myproject.wsgi"]
```

Then either mount the key file and add `"-k", "prod=/run/secrets/prod.key"` before the `"--"` of the entrypoint
(first line below), or pass the variable from the calling shell without writing its value on the command line
(second line):

```sh
docker run -v "$PWD/prod.key:/run/secrets/prod.key:ro" -e ENV_STORE_CONNECTION example/app
docker run -e ENV_STORE_KEY_PROD -e ENV_STORE_CONNECTION example/app
```

`-e NAME` without a value copies the variable from the environment of `docker run`. Never put a key into the image:
`ENV` and `ARG` values end up in the image's history for everyone who can pull it.

**CI.** Store the key text as a masked secret of your CI system and expose it as `ENV_STORE_KEY_<STORE>`, for
example in GitHub Actions:

```yaml
    steps:
      - run: envs --noinput run base prod -- ./deploy.sh
        env:
          ENV_STORE_CONNECTION: ${{ secrets.ENV_STORE_CONNECTION }}
          ENV_STORE_KEY_PROD: ${{ secrets.ENV_STORE_KEY_PROD }}
```

If the CI system can write secrets to files, prefer those with `-k`; the
[CI recipe](cli.md#ci-no-prompts-key-from-a-secret) in the CLI reference shows that and `-k -` on stdin.

## Security notes

**`envs run` strips the key variables.** It removes every `ENV_STORE_KEY_*` variable from the environment of the
command it starts, so your program never inherits a key (on POSIX, `envs` replaces itself with the command, so no
process with the key remains):

```console
$ ENV_STORE_KEY_PROD="$(cat prod.key)" envs --noinput run base prod -- env | grep -E 'ENV_STORE_KEY|DB_'
DB_HOST=localhost
DB_PASSWORD=hunter2
```

The Python library does not change `os.environ` apart from what `load()` or `apply()` writes, so the variable
stays in your process; drop it after loading, as in the [Django example](#heroku). The platform keeps showing the
key to everyone who may read the configuration either way.

**What encryption protects in a deployment.** Encryption protects the **backend and its backups**: whoever can read
the database, the JSON or TOML files or a dump of them sees store names and metadata, but no variable names and no
values. That covers a leaked database password or dump, a database shared with other apps, and backups kept
elsewhere.

It does **not** protect against someone who can read the deployment's configuration. When the connection and the
key live in the same place (Heroku config vars, one Kubernetes Secret, the CI secrets of one project), anyone who
can read that place, exec into a container or read a process's environment gets both, and with them every value.
Guard those permissions like the secrets themselves. Keeping the key in its own Secret, with its own access rules,
and mounting it as a file narrows who can see it, but anyone who can read that Secret or the file still has it.

**Rotate with `rekey`.** To replace a key that may have leaked, re-encrypt the store with a new key and then give
the deployment the new one. The old key may come from `-k` or from the variable:

```console
$ envs --noinput rekey -s prod -k prod.key --generate-key prod-2027.key
rekeyed store 'prod' (keyfile)
$ ENV_STORE_KEY_PROD="$(cat prod-2027.key)" envs --noinput run base prod -- printenv DB_PASSWORD
hunter2
```

The old key stops working at once, so update the deployment right away:
`heroku config:set ENV_STORE_KEY_PROD="$(cat prod-2027.key)"` (which restarts the dynos), or update the Secret and
restart the pods. Processes that are already running keep the values they loaded; processes that start between the
`rekey` and the update fail with exit code 4. Then delete the old key file and replace it in every other place
that holds it. A key that leaked may also have exposed the values: if so, rotate those secrets at their source
too. See [Encryption and keys](encryption.md#rotate-a-key-envs-rekey) for passphrases and switching modes.
