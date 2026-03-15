
CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TABLE public.environment_store (
    id integer NOT NULL,
    is_secret boolean DEFAULT false NOT NULL,
    organization character varying(100),
    project character varying(100),
    environment character varying(100),
    service character varying(100),
    var character varying(100),
    var_value text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT environment_store_hierarchy_check CHECK ((((project IS NULL) OR (organization IS NOT NULL)) AND ((environment IS NULL) OR ((organization IS NOT NULL) AND (project IS NOT NULL))) AND ((service IS NULL) OR ((organization IS NOT NULL) AND (project IS NOT NULL) AND (environment IS NOT NULL)))))
);

CREATE SEQUENCE public.environment_store_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.environment_store_id_seq OWNED BY public.environment_store.id;

ALTER TABLE ONLY public.environment_store ALTER COLUMN id SET DEFAULT nextval('public.environment_store_id_seq'::regclass);

ALTER TABLE ONLY public.environment_store
    ADD CONSTRAINT environment_store_organization_project_environment_service__key UNIQUE (organization, project, environment, service, var);

ALTER TABLE ONLY public.environment_store
    ADD CONSTRAINT environment_store_pkey PRIMARY KEY (id);

CREATE TRIGGER update_environment_store_updated_at BEFORE UPDATE ON public.environment_store FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
