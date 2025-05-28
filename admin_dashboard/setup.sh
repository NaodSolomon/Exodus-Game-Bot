#!/bin/bash

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install required packages
pip install flask bcrypt

# Copy static assets
mkdir -p src/static/images
cp -r ../upload/*.jpg src/static/images/

# Create categories template
cat > src/templates/categories.html << 'EOL'
{% extends 'base.html' %}

{% block title %}Categories | Exodus Game Store Admin{% endblock %}

{% block content %}
<div class="flex justify-between items-center mb-6">
    <div>
        <h1 class="text-2xl font-bold text-gray-800">Category Management</h1>
        <p class="text-gray-600">Manage game platforms</p>
    </div>
    <a href="{{ url_for('add_category') }}" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-4 rounded-lg flex items-center">
        <i class="fas fa-plus mr-2"></i> Add New Category
    </a>
</div>

<div class="bg-white overflow-hidden shadow-md rounded-lg">
    <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Platform</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Games Count</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
                {% for platform in platforms %}
                <tr>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="text-sm font-medium text-gray-900">{{ platform.platform }}</div>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="text-sm text-gray-900">{{ platform.game_count }}</div>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <div class="flex space-x-2">
                            <a href="{{ url_for('edit_category', category_name=platform.platform) }}" class="text-indigo-600 hover:text-indigo-900">
                                <i class="fas fa-edit"></i> Edit
                            </a>
                            {% if platform.game_count == 0 %}
                            <form action="{{ url_for('delete_category', category_name=platform.platform) }}" method="POST" class="inline" onsubmit="return confirm('Are you sure you want to delete this category?');">
                                <button type="submit" class="text-red-600 hover:text-red-900">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </form>
                            {% endif %}
                        </div>
                    </td>
                </tr>
                {% endfor %}
                {% if not platforms %}
                <tr>
                    <td colspan="3" class="px-6 py-4 text-center text-sm text-gray-500">No categories found</td>
                </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</div>
{% endblock %}
EOL

# Create add_category template
cat > src/templates/add_category.html << 'EOL'
{% extends 'base.html' %}

{% block title %}Add Category | Exodus Game Store Admin{% endblock %}

{% block content %}
<div class="mb-6">
    <div class="flex justify-between items-center">
        <div>
            <h1 class="text-2xl font-bold text-gray-800">Add New Category</h1>
            <p class="text-gray-600">Create a new platform category</p>
        </div>
        <a href="{{ url_for('categories') }}" class="bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium py-2 px-4 rounded-lg flex items-center">
            <i class="fas fa-arrow-left mr-2"></i> Back to Categories
        </a>
    </div>
</div>

<div class="bg-white p-6 rounded-lg shadow-md mb-6">
    <form method="POST" action="{{ url_for('add_category') }}" class="space-y-6">
        <div>
            <label for="name" class="block text-sm font-medium text-gray-700">Category Name</label>
            <input type="text" name="name" id="name" required class="mt-1 focus:ring-indigo-500 focus:border-indigo-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md">
            <p class="mt-1 text-xs text-gray-500">Enter the platform name (e.g., PS5, Xbox, PC)</p>
        </div>
        
        <div>
            <label for="description" class="block text-sm font-medium text-gray-700">Description (Optional)</label>
            <textarea name="description" id="description" rows="3" class="mt-1 focus:ring-indigo-500 focus:border-indigo-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md"></textarea>
        </div>
        
        <div class="flex justify-end space-x-3">
            <a href="{{ url_for('categories') }}" class="bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium py-2 px-4 rounded-lg">Cancel</a>
            <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-4 rounded-lg">Add Category</button>
        </div>
    </form>
</div>
{% endblock %}
EOL

# Create edit_category template
cat > src/templates/edit_category.html << 'EOL'
{% extends 'base.html' %}

{% block title %}Edit Category | Exodus Game Store Admin{% endblock %}

{% block content %}
<div class="mb-6">
    <div class="flex justify-between items-center">
        <div>
            <h1 class="text-2xl font-bold text-gray-800">Edit Category</h1>
            <p class="text-gray-600">Update platform category details</p>
        </div>
        <a href="{{ url_for('categories') }}" class="bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium py-2 px-4 rounded-lg flex items-center">
            <i class="fas fa-arrow-left mr-2"></i> Back to Categories
        </a>
    </div>
</div>

<div class="bg-white p-6 rounded-lg shadow-md mb-6">
    <form method="POST" action="{{ url_for('edit_category', category_name=category.name) }}" class="space-y-6">
        <div>
            <label for="name" class="block text-sm font-medium text-gray-700">Category Name</label>
            <input type="text" name="name" id="name" required value="{{ category.name }}" class="mt-1 focus:ring-indigo-500 focus:border-indigo-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md">
            <p class="mt-1 text-xs text-gray-500">Enter the platform name (e.g., PS5, Xbox, PC)</p>
        </div>
        
        <div>
            <label for="description" class="block text-sm font-medium text-gray-700">Description (Optional)</label>
            <textarea name="description" id="description" rows="3" class="mt-1 focus:ring-indigo-500 focus:border-indigo-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md">{{ category.description }}</textarea>
        </div>
        
        <div class="flex justify-end space-x-3">
            <a href="{{ url_for('categories') }}" class="bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium py-2 px-4 rounded-lg">Cancel</a>
            <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-4 rounded-lg">Update Category</button>
        </div>
    </form>
</div>
{% endblock %}
EOL

echo "Setup completed successfully!"
