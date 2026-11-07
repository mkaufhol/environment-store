# Deployment: keys on Heroku and Kubernetes

A deployed app has to read its encrypted stores without anyone typing a key. This page shows the two ways to hand
the key over on a platform such as Heroku or Kubernetes: as an environment variable `ENV_STORE_KEY_<STORE>`, or as
a mounted file passed with `-k` or `[keys]`. It also says what encryption still protects once the key sits in the
deployment's configuration.

The `envs` commands on this page were run against the real CLI. The Heroku and Kubernetes snippets were not run for
this guide; adapt them to your setup.

- [The key variable `ENV_STORE_KEY_<STORE>`](#the-key-variable-env_store_key_store)
- [Heroku](#heroku)
- [Kubernetes](#kubernetes)
- [What encryption protects in a deployment](#what-encryption-protects-in-a-deployment)

## The key variable `ENV_STORE_KEY_<STORE>`

`envs`, the Python library and the TUI read an existing store's key or passphrase from the environment variable
`ENV_STORE_KEY_<STORE>`. `<STORE>` is the store name in upper case with `-` turned into `_`:

| Store | Variable |
|---|---|
| `prod` | `ENV_STORE_KEY_PROD` |
| `customer-a` | `ENV_STORE_KEY_CUSTOMER_A` |

The value is what a `-k` file would hold: the key line (`envstore-key-v1:…`, from `envs keygen -`) for a key file
store, the passphrase for a passphrase store. One trailing newline is removed.

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

  A key that does not fit the store gives the usual `cannot decrypt store 'prod'` error, also exit code 4.
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
- **Not passed on.** `envs run` removes every `ENV_STORE_KEY_*` variable from the environment of the command it
  starts, so your program never inherits a key:

  ```console
  $ ENV_STORE_KEY_PROD="$(cat prod.key)" envs --noinput run base prod -- env | grep -E 'ENV_STORE_KEY|DB_'
  DB_HOST=localhost
  DB_PASSWORD=hunter2
  ```

  The Python library does not change `os.environ` apart from what `apply()` writes.

## Heroku

Heroku has no files you can ship next to a dyno, so its config vars are the natural place for the key. Set the
connection and one key variable per encrypted store:

```sh
heroku config:set ENV_STORE_CONNECTION='postgresql://…' ENV_STORE_KEY_PROD="$(cat prod.key)"
```

Start the app through `envs run` in the `Procfile`. `--noinput` makes a missing key fail at once with exit code 4
instead of waiting for input:

```text
web: envs --noinput run base prod -- gunicorn app.wsgi
```

`envs run` strips `ENV_STORE_KEY_PROD` before it starts `gunicorn`. If the app loads its stores itself with the
Python library instead, `environment_store.load("base", "prod", noinput=True)` reads the same variable.

## Kubernetes

Put the key into a Secret:

```sh
kubectl create secret generic envs-keys --from-file=prod.key=prod.key
```

### As a mounted file (recommended)

Mount the Secret as a file and pass its path with `-k` (or list it under `[keys]` in a project file in the image).
The key then never enters the process environment, where every child process and every tool that can read the
environment would see it:

```yaml
spec:
  containers:
    - name: app
      image: example/app
      command: ["envs", "--noinput", "run", "base", "prod", "-k", "prod=/etc/envs/prod.key", "--", "./serve"]
      env:
        - name: ENV_STORE_CONNECTION
          valueFrom: {secretKeyRef: {name: envs-connection, key: url}}
      volumeMounts:
        - {name: envs-keys, mountPath: /etc/envs, readOnly: true}
  volumes:
    - name: envs-keys
      secret: {secretName: envs-keys, defaultMode: 0400}
```

With a project file instead of `-k`:

```toml
stores = ["base", "prod"]

[keys]
prod = "/etc/envs/prod.key"
```

### As an environment variable

If mounting files is not an option, map the Secret to the key variable:

```yaml
      env:
        - name: ENV_STORE_KEY_PROD
          valueFrom: {secretKeyRef: {name: envs-keys, key: prod.key}}
      command: ["envs", "--noinput", "run", "base", "prod", "--", "./serve"]
```

## What encryption protects in a deployment

Encryption protects the **backend and its backups**: whoever can read the database, the JSON or TOML files or a
dump of them sees store names and metadata, but no variable names and no values.

It does **not** protect against someone who can read the deployment's configuration. Heroku config vars, a
Kubernetes Secret, or the right to exec into a pod or read its environment all give the key, and with access to the
backend that means every value. Guard those permissions like the secrets themselves. A mounted file keeps the key
out of the process environment, but anyone who can read the Secret or the file still has it.

See [Encryption and keys](encryption.md) for key files, passphrases and key rotation.
