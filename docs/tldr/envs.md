# envs

> Keep environment variables in named, optionally encrypted stores and load them anywhere.
> The backend is chosen with `--connection` or `$ENV_STORE_CONNECTION`.
> More information: <https://github.com/mkaufhol/environment-store>.

- List all stores in a directory of JSON files:

`envs --connection json://{{path/to/directory}} ls-store`

- Create a store:

`envs create-store {{store_name}}`

- Create an encrypted store with a new key file:

`envs create-store --encrypt --generate-key {{path/to/key_file}} {{store_name}}`

- Set variables in a plaintext store:

`envs set --store {{store_name}} {{KEY1=value1 KEY2=value2 ...}}`

- Set a variable in an encrypted store, reading its value from a file:

`envs set --store {{store_name}} --key {{path/to/key_file}} {{KEY}} < {{path/to/value_file}}`

- List the merged variables of several stores with their values (the last store wins):

`envs ls --values {{store1 store2 ...}}`

- Export the merged variables of several stores to a dotenv file:

`envs export --file {{path/to/file.env}} {{store1 store2 ...}}`

- Run a command with the merged variables of several stores:

`envs run {{store1 store2 ...}} -- {{command}}`
