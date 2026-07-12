CREATE_OWNER_QUERY = """
INSERT INTO owners (
    full_name,
    email,
    phone,
    company_name
)
VALUES (
    :full_name,
    :email,
    :phone,
    :company_name
)
RETURNING *
"""