import psycopg2

def generate():
    conn = psycopg2.connect('postgresql://airflow:airflow@localhost:5432/vsf_database')
    cur = conn.cursor()
    cur.execute('SELECT id, images FROM attractions WHERE images IS NOT NULL;')
    rows = cur.fetchall()
    
    with open('d:/Git repo/vsf-project/update_images.sql', 'w', encoding='utf-8') as f:
        f.write('BEGIN;\n')
        for row in rows:
            id_val = row[0]
            images = row[1]
            if images:
                # format the array for SQL
                array_str = ', '.join([f"'{img}'" for img in images])
                f.write(f"UPDATE attractions SET images = ARRAY[{array_str}] WHERE id = '{id_val}';\n")
        f.write('COMMIT;\n')
    print('Created update_images.sql')

if __name__ == '__main__':
    generate()
