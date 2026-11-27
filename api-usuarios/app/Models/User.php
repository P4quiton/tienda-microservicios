<?php

namespace App\Models;

use Database\Factories\UserFactory;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Foundation\Auth\User as Authenticatable;
use Illuminate\Support\Str;

class User extends Authenticatable
{
    /** @use HasFactory<UserFactory> */
    use HasFactory, HasUuids;

    protected $table = 'usuarios';

    protected $fillable = [
        'nombre',
        'correo',
        'password',
    ];

    protected $hidden = [
        'password',
    ];

    protected $attributes = [
        'role' => 'cliente',
    ];

    public function newUniqueId(): string
    {
        return (string) Str::uuid();
    }

    protected function casts(): array
    {
        return [
            'password' => 'hashed',
        ];
    }
}
