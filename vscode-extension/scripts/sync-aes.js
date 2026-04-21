const fs = require('fs');
const path = require('path');

// Paths (relative to this script)
const ROOT_DIR = path.resolve(__dirname, '../../');
const MASTER_SCHEMA_PATH = path.join(ROOT_DIR, 'spec/aes/aes.schema.json');
const DEFINITIONS_DIR = path.join(ROOT_DIR, 'spec/aes/definitions');
const OUTPUT_PATH = path.join(ROOT_DIR, 'vscode-extension/aes.schema.json');

function bundleSchema() {
    console.log('--- AgentV Schema Bundler ---');
    console.log(`Master Source: ${MASTER_SCHEMA_PATH}`);

    if (!fs.existsSync(MASTER_SCHEMA_PATH)) {
        console.error('Error: Master AES schema not found.');
        process.exit(1);
    }

    const masterSchema = JSON.parse(fs.readFileSync(MASTER_SCHEMA_PATH, 'utf8'));

    // 1. Title/Version update
    masterSchema.title = "Agent Eval Specification (AES) v1.4.1 [Bundled]";

    // 2. Resolve $ref for core properties
    for (const prop in masterSchema.properties) {
        const value = masterSchema.properties[prop];
        if (value && value.$ref) {
            const refPath = value.$ref;
            if (refPath.startsWith('definitions/')) {
                const defFile = refPath.split('/')[1];
                const defPath = path.join(DEFINITIONS_DIR, defFile);

                console.log(`  > Resolving ${prop} from ${defPath}`);
                if (fs.existsSync(defPath)) {
                    const defContent = JSON.parse(fs.readFileSync(defPath, 'utf8'));
                    // We discard the root schema metadata from the definition file
                    // and keep just the type/properties
                    masterSchema.properties[prop] = defContent;
                    delete masterSchema.properties[prop].$schema;
                    delete masterSchema.properties[prop].title;
                } else {
                    console.warn(`  ! Warning: Definition not found at ${defPath}`);
                }
            }
        }
    }

    // 3. Write flattened schema
    console.log(`Writing bundled schema to ${OUTPUT_PATH}`);
    fs.writeFileSync(OUTPUT_PATH, JSON.stringify(masterSchema, null, 4), 'utf8');
    console.log('--- Bundling Complete ---');
}

bundleSchema();
